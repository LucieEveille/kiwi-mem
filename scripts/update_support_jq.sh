#!/usr/bin/env bash
# jq fallback; dotenv and state are data, never shell code.
set -uo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read_env() {
    local value
    value="$(awk -v key="$1" '
      $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
        sub("^[[:space:]]*" key "[[:space:]]*=", ""); value=$0
      }
      END {gsub(/^[[:space:]]+|[[:space:]]+$/, "", value);
        if ((substr(value,1,1)=="\"" && substr(value,length(value),1)=="\"") ||
            (substr(value,1,1)==sprintf("%c",39) && substr(value,length(value),1)==sprintf("%c",39)))
          value=substr(value,2,length(value)-2);
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", value); print value}' .env 2>/dev/null)"
    case "$1" in
      MCP_ALLOWED_HOSTS) printf '%s' "${MCP_ALLOWED_HOSTS-$value}" ;;
      PORT) printf '%s' "${PORT-$value}" ;;
    esac
}
probe() {
    local port="$1" path="$2" payload="${3:-}" code
    local tmp
    tmp="$(mktemp)" || return 2
    local args=(curl -sS --max-time 5 -o "$tmp" -w '%{http_code}')
    if [ -n "$payload" ]; then
        args+=(-X POST -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' --data "$payload")
    fi
    if command -v curl >/dev/null 2>&1; then
        code="$("${args[@]}" "http://127.0.0.1:$port$path" 2>/dev/null)" || code=0
    else
        args=(wget -q -T 5 -t 1 --max-redirect=0 --server-response -O "$tmp")
        [ -z "$payload" ] || args+=(--header='Accept: application/json, text/event-stream' --header='Content-Type: application/json' --post-data="$payload")
        if "${args[@]}" "http://127.0.0.1:$port$path" 2>"$tmp.headers"; then
            code="$(sed -n 's/.*HTTP\/[^ ]* \([0-9][0-9][0-9]\).*/\1/p' "$tmp.headers" | tail -n 1)"
        else code=0; fi
        rm -f "$tmp.headers"
    fi
    if [ "$code" != 200 ]; then rm -f "$tmp"; return 1; fi
    if ! jq -ce . "$tmp" 2>/dev/null; then
        sed -n 's/^data: *//p' "$tmp" | jq -ce 'select(.id==1)' 2>/dev/null
    fi
    local result=$?
    rm -f "$tmp"
    return "$result"
}
command="${1:-}"; shift
case "$command" in
 port)
    value="$(read_env PORT)"
    if [[ "$value" =~ ^[0-9]{1,5}$ ]] && [ "$((10#$value))" -ge 1 ] && [ "$((10#$value))" -le 65535 ]; then printf '%s\n' "$value"; else echo 8080; fi ;;
 preflight)
    target="$1"; compose="$2"; port="$3"
    gate="$(git show "$target:scripts/upgrade_gates.json" 2>/dev/null | jq -er '.gates.mcp_access_control|tostring' 2>/dev/null)" || { echo '预检跳过：无法读取升级门'; exit 0; }
    [ "$gate" = true ] || exit 0
    if ! probe "$port" /admin/mcp-access-status | jq -e '.foreign_host_seen==true' >/dev/null 2>&1; then
        echo '预检：未能验证 MCP 远程使用情况，仅提示——若你用域名访问 MCP，请先登记'; exit 0
    fi
    hosts="$(read_env MCP_ALLOWED_HOSTS)"
    rendered="$($compose config --format json 2>/dev/null)" &&
      if printf '%s' "$rendered" | jq -e '.services["kiwi-mem"].environment|has("MCP_ALLOWED_HOSTS")' >/dev/null 2>&1; then
        hosts="$(printf '%s' "$rendered" | jq -r '.services["kiwi-mem"].environment.MCP_ALLOWED_HOSTS // ""')"
      fi
    printf '%s' "$hosts" | jq -Rse -L "$BASE" 'include "prep_authority"; split(",")|any(.[]; gsub("^\\s+|\\s+$"; "")|validhost)' >/dev/null 2>&1 && exit 0
    exit 3 ;;
 save)
    prev="$1"; target="$2"; compose="$3"; port="$4"; backup="$5"; shift 5
    tmp="$(mktemp .update-state-XXXXXX)" || exit 2
    if jq -n --arg prev "$prev" --arg target "$target" --arg compose "$compose" --arg port "$port" --arg backup "$backup" --args \
       '{prev:$prev,target:$target,compose:$compose,port:$port,backup_file:$backup,stage:"post-merge",resumed:1,args:$ARGS.positional}' -- "$@" > "$tmp"; then
       mv -f -- "$tmp" .update-state.json
    else rm -f -- "$tmp"; exit 2; fi ;;
 load)
    [ "$1" = .update-state.json ] || exit 2
    head="$(git rev-parse HEAD)"
    jq -er --arg head "$head" '
      select(.stage=="post-merge" and .resumed==1 and .target==$head) |
      select((.prev|test("^[0-9a-f]{40,64}$")) and (.target|test("^[0-9a-f]{40,64}$"))) |
      select(.compose=="docker compose" or .compose=="docker-compose") |
      select((.port|test("^[0-9]{1,5}$")) and (.port|tonumber)>=1 and (.port|tonumber)<=65535) |
      select((.backup_file|type)=="string" and (.backup_file|test("[\\r\\n\\u0000]")|not)) |
      select((.args|type)=="array" and all(.args[];type=="string")) |
      .prev,.target,.compose,.port,.backup_file' "$1" ;;
 probe)
    probe "$1" /memory/mcp '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"update.sh","version":"1.7.0"}}}' |
      jq -e '.id==1 and has("result") and (has("error")|not)' >/dev/null ;;
 *) exit 2 ;;
esac
