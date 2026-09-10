# Dependency-free jq fallback for hosts without Python. No values are printed.
def ipv4:
  split(".") as $p | ($p|length)==4 and all($p[]; test("^(0|[1-9][0-9]{0,2})$") and (tonumber <= 255));
def ipv6:
  . as $raw |
  (if contains(".") then
     split(":") | .[-1] as $tail |
     if ($tail|ipv4) then .[:-1] + ["0","0"] | join(":") else "invalid" end
   else . end) as $v |
  ($v|split("::")) as $s |
  ([$s[]|split(":")[]|select(length>0)]) as $parts |
  ($s|length)<=2 and all($parts[]; test("^[0-9A-Fa-f]{1,4}$")) and
  (if ($s|length)==2 then ($parts|length)<8 and ($s[0]|endswith(":")|not) and ($s[1]|startswith(":")|not)
   else ($parts|length)==8 and ($v|startswith(":")|not) and ($v|endswith(":")|not) end);
def validhost:
  if type != "string" or length==0 or test("[\\s\\x00-\\x20\\x7f/@?#%\\\\]") then false
  else
    (try capture("^(?<host>\\[[^]]+\\]|[^:]+)(?::(?<port>[^:]*))?$") catch null) as $p |
    if $p==null then false else
      (($p.port // "") as $port |
       if endswith(":") then false
       elif $port=="" or $port=="*" then true
       else ($port|test("^[0-9]{1,5}$")) and ($port|tonumber)>=1 and ($port|tonumber)<=65535 end) and
      ($p.host | if startswith("[") then .[1:-1]|ipv6
       else rtrimstr(".") | length<=253 and
         all(split(".")[]; test("^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")) end)
    end
  end;
