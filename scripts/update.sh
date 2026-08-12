#!/usr/bin/env bash
# ============================================================
# kiwi-mem 一键更新脚本
# ============================================================
# 把 kiwi-mem 更新到 GitHub 上的最新版本。
#
#   bash scripts/update.sh                # 更新（会先问一句）
#   bash scripts/update.sh --yes          # 不问，直接更新
#   bash scripts/update.sh --check        # 只看有没有新版本，不碰服务
#   bash scripts/update.sh --auto         # 定时任务用：没新版本就静默退出
#   bash scripts/update.sh --install-cron # 装上「每天凌晨 4 点自动更新」
#   bash scripts/update.sh --force        # 本地改过文件时，丢弃改动强制更新
#   bash scripts/update.sh --no-backup    # 跳过数据库备份（不推荐）
#
# 脚本做的事：备份数据库 → 拉最新代码 → 重建容器 → 健康检查。
# 任何一步失败都会自动回滚到更新前的版本，服务不会挂在半路。
#
# 你的 .env 配置、管理面板里配的供应商、所有记忆数据都不会被动到。
# ============================================================

set -uo pipefail

# ---- 参数 ----
ASSUME_YES=0
CHECK_ONLY=0
AUTO_MODE=0
FORCE=0
DO_BACKUP=1
INSTALL_CRON=0

for arg in "$@"; do
    case "$arg" in
        --yes|-y)       ASSUME_YES=1 ;;
        --check)        CHECK_ONLY=1 ;;
        --auto)         AUTO_MODE=1; ASSUME_YES=1 ;;
        --force)        FORCE=1 ;;
        --no-backup)    DO_BACKUP=0 ;;
        --install-cron) INSTALL_CRON=1 ;;
        --help|-h)      awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *)              echo "未知参数：$arg（用 --help 看用法）"; exit 2 ;;
    esac
done

# ---- 输出 ----
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_DIM=''; C_OFF=''
fi
# 定时任务模式先闭嘴，确认真有新版本了再开口 —— 免得日志天天堆没用的行
QUIET=$AUTO_MODE
log()  { [ "$QUIET" = "1" ] && return 0; echo "${C_DIM}[$(date '+%Y-%m-%d %H:%M:%S')]${C_OFF} $*"; }
ok()   { [ "$QUIET" = "1" ] && return 0; echo "${C_GREEN}✅ $*${C_OFF}"; }
warn() { [ "$QUIET" = "1" ] && return 0; echo "${C_YELLOW}⚠️  $*${C_OFF}"; }
die()  { echo "${C_RED}❌ $*${C_OFF}" >&2; exit 1; }

# ---- 定位仓库根目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR" || die "进不去 kiwi-mem 目录：$REPO_DIR"

[ -f docker-compose.yml ] || die "这里不像 kiwi-mem 目录（找不到 docker-compose.yml）：$REPO_DIR"
git rev-parse --git-dir >/dev/null 2>&1 || die "这个目录不是 git 仓库，没法自动更新。
请重新用 git clone https://github.com/LucieEveille/kiwi-mem.git 部署一次。"

# ---- 装定时任务 ----
if [ "$INSTALL_CRON" = "1" ]; then
    command -v crontab >/dev/null 2>&1 || die "服务器上没有 crontab，装不了定时任务。"
    CRON_LINE="0 4 * * * cd $REPO_DIR && bash scripts/update.sh --auto >> $REPO_DIR/update.log 2>&1"
    CURRENT="$(crontab -l 2>/dev/null || true)"
    if echo "$CURRENT" | grep -qF "scripts/update.sh --auto"; then
        ok "定时更新任务已经装过了，不用重复装。"
        echo "${C_DIM}当前任务：$(echo "$CURRENT" | grep -F 'scripts/update.sh --auto')${C_OFF}"
    else
        printf '%s\n%s\n' "$CURRENT" "$CRON_LINE" | sed '/^$/d' | crontab - \
            || die "写入 crontab 失败。"
        ok "装好了！以后每天凌晨 4 点会自动检查并更新 kiwi-mem。"
        echo "   有没有更新过、更新成不成功，都记在：$REPO_DIR/update.log"
        echo "   想取消：crontab -e，删掉那一行就行。"
    fi
    exit 0
fi

# ---- 看看有没有新版本 ----
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
REMOTE="$(git remote | head -n 1)"
[ -n "$REMOTE" ] || die "仓库没配 remote，不知道去哪拉代码。"

# 优先跟随上游分支（clone 出来的仓库天然带上游），否则退回同名分支 / main
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
if [ -n "$UPSTREAM" ]; then
    REMOTE="${UPSTREAM%%/*}"
    BRANCH="${UPSTREAM#*/}"
elif [ "$BRANCH" = "HEAD" ] || [ -z "$BRANCH" ]; then
    BRANCH="main"
fi

log "检查更新中（$REMOTE/$BRANCH）…"
FETCH_OK=0
for delay in 0 2 4 8; do
    [ "$delay" -gt 0 ] && sleep "$delay"
    if git fetch "$REMOTE" "$BRANCH" --quiet 2>/dev/null; then FETCH_OK=1; break; fi
    # 远程没有同名分支（比如本地切过分支）→ 退回主分支
    if ! git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1 && [ "$BRANCH" != "main" ]; then
        warn "远程没有 $BRANCH 分支，改用 main。"
        BRANCH="main"
        continue
    fi
    [ "$AUTO_MODE" = "0" ] && warn "连 GitHub 失败，重试中…"
done
[ "$FETCH_OK" = "1" ] || die "连不上 GitHub，拉不到最新代码。等会儿再试试。"

LOCAL="$(git rev-parse HEAD)"
LATEST="$(git rev-parse "$REMOTE/$BRANCH")"

if [ "$LOCAL" = "$LATEST" ]; then
    [ "$AUTO_MODE" = "1" ] && exit 0   # 定时任务模式：没更新就闭嘴
    ok "已经是最新版了，不用更新。"
    echo "${C_DIM}当前版本：$(git log -1 --format='%h %s (%cd)' --date=format:'%Y-%m-%d')${C_OFF}"
    exit 0
fi

QUIET=0   # 确实有新版本，从这里开始正常输出（定时任务的日志也从这里才有内容）
COUNT="$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo '?')"
echo
[ "$AUTO_MODE" = "1" ] && echo "${C_DIM}===== 自动更新 $(date '+%Y-%m-%d %H:%M:%S') =====${C_OFF}"
echo "${C_YELLOW}🥝 发现新版本！有 $COUNT 个更新：${C_OFF}"
git log --format='   • %s' "HEAD..$REMOTE/$BRANCH" | head -n 20
[ "$COUNT" != "?" ] && [ "$COUNT" -gt 20 ] && echo "   …还有 $((COUNT - 20)) 个"
echo

if [ "$CHECK_ONLY" = "1" ]; then
    echo "想更新的话，跑：${C_GREEN}bash scripts/update.sh${C_OFF}"
    exit 0
fi

# ---- 本地有没有改过文件（先查前置条件，再问要不要更新）----
DIRTY="$(git status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
    if [ "$FORCE" = "1" ]; then
        warn "本地改动会被丢弃（你加了 --force）："
        echo "$DIRTY" | sed 's/^/   /'
    else
        echo "${C_RED}❌ 本地改过仓库里的文件，怕覆盖掉，先停一下：${C_OFF}"
        echo "$DIRTY" | sed 's/^/   /'
        echo
        echo "   这些改动不重要 → 丢掉它们直接更新：${C_GREEN}bash scripts/update.sh --force${C_OFF}"
        echo "   这些改动要留着 → 先跑 ${C_GREEN}git stash${C_OFF} 存起来，再重新跑本脚本"
        echo "   ${C_DIM}（.env 配置文件不在此列，永远不会被更新覆盖）${C_OFF}"
        exit 1
    fi
fi

# ---- 找 docker compose ----
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    die "找不到 docker compose 命令。先装 Docker：curl -fsSL https://get.docker.com | sh"
fi

if [ "$ASSUME_YES" = "0" ]; then
    printf "现在更新吗？更新过程大约 1-3 分钟，期间服务会短暂中断。[Y/n] "
    read -r reply
    case "$reply" in
        [Nn]*) echo "那就先不更新。"; exit 0 ;;
    esac
fi

# ---- 备份数据库 ----
BACKUP_FILE=""
if [ "$DO_BACKUP" = "1" ]; then
    DB_CID="$($COMPOSE ps -q db 2>/dev/null || true)"
    if [ -n "$DB_CID" ] && [ "$(docker inspect -f '{{.State.Running}}' "$DB_CID" 2>/dev/null)" = "true" ]; then
        mkdir -p backups
        BACKUP_FILE="backups/kiwi-mem-$(date '+%Y%m%d-%H%M%S').sql.gz"
        log "备份数据库到 $BACKUP_FILE …"
        if $COMPOSE exec -T db sh -c \
            'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
            2>/dev/null | gzip > "$BACKUP_FILE"; then
            ok "备份好了（$(du -h "$BACKUP_FILE" | cut -f1)）"
            # 只留最近 7 份，别把硬盘塞满
            ls -1t backups/kiwi-mem-*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
        else
            rm -f "$BACKUP_FILE"; BACKUP_FILE=""
            warn "备份没成功，但更新本身不会删数据（记忆都在 Docker 数据卷里），继续。"
        fi
    else
        warn "数据库容器没在跑，跳过备份。"
    fi
fi

# ---- 拉代码 ----
PREV_COMMIT="$LOCAL"
log "拉取最新代码…"
if [ "$FORCE" = "1" ]; then
    git reset --hard "$REMOTE/$BRANCH" --quiet || die "更新代码失败。"
else
    git merge --ff-only "$REMOTE/$BRANCH" --quiet || die "更新代码失败（本地和远程分叉了）。
可以用 bash scripts/update.sh --force 强制更新到最新版。"
fi
ok "代码已更新到 $(git log -1 --format='%h %s')"

# ---- 重建并启动 ----
log "重建容器并启动（第一次会久一点，耐心等）…"
if ! $COMPOSE up -d --build; then
    warn "启动失败，正在回滚到更新前的版本…"
    git reset --hard "$PREV_COMMIT" --quiet
    $COMPOSE up -d --build >/dev/null 2>&1
    die "更新失败，已回滚到旧版本，服务应该恢复了。
把上面的报错发给库作者看看。$([ -n "$BACKUP_FILE" ] && echo "
数据库备份在：$REPO_DIR/$BACKUP_FILE")"
fi

# ---- 健康检查 ----
PORT="$(grep -E '^\s*PORT=' .env 2>/dev/null | tail -n 1 | cut -d= -f2 | tr -d ' \r')"
[ -n "${PORT:-}" ] || PORT=8080
HEALTH_URL="http://127.0.0.1:$PORT/"

if command -v curl >/dev/null 2>&1; then
    PROBE=(curl -fsS --max-time 5 "$HEALTH_URL")
elif command -v wget >/dev/null 2>&1; then
    PROBE=(wget -q -T 5 -O - "$HEALTH_URL")
else
    PROBE=()
fi

if [ ${#PROBE[@]} -gt 0 ]; then
    log "等服务起来（最多 90 秒）…"
    HEALTHY=0
    for _ in $(seq 1 30); do
        if "${PROBE[@]}" >/dev/null 2>&1; then HEALTHY=1; break; fi
        sleep 3
    done
    if [ "$HEALTHY" = "0" ]; then
        warn "服务起不来，正在回滚到更新前的版本…"
        git reset --hard "$PREV_COMMIT" --quiet
        $COMPOSE up -d --build >/dev/null 2>&1
        echo
        echo "${C_DIM}--- 新版本的错误日志（最后 40 行）---${C_OFF}"
        $COMPOSE logs --tail=40 kiwi-mem 2>&1 | sed 's/^/   /' || true
        die "更新失败，已回滚到旧版本，服务应该恢复了。
把上面的日志发给库作者看看。$([ -n "$BACKUP_FILE" ] && echo "
数据库备份在：$REPO_DIR/$BACKUP_FILE")"
    fi
else
    warn "服务器上没有 curl / wget，跳过健康检查。"
fi

echo
ok "更新完成！现在是最新版：$(git log -1 --format='%h %s')"
echo "${C_DIM}   数据库结构已自动跟上，你的记忆、配置、供应商设置都还在。${C_OFF}"
[ -n "$BACKUP_FILE" ] && echo "${C_DIM}   更新前的数据库备份：$BACKUP_FILE${C_OFF}"
echo "${C_DIM}   有问题看日志：$COMPOSE logs -f kiwi-mem${C_OFF}"
exit 0
