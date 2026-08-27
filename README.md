# 🥝 kiwi-mem

**大多数 AI 记忆系统是数据库。kiwi-mem 是一颗大脑。**

[English Version →](README_EN.md)

---

## 它做了什么

kiwi-mem 让你的 AI 拥有像人脑一样运转的长期记忆。

不是"把聊天记录存起来，用的时候搜一下"——是真的像人一样记东西：不常提起的事会慢慢淡忘，反复聊到的事越记越牢，睡一觉醒来会把零散的碎片整理成更深的理解，去年的事只记得个大概，昨天的事记得很清楚。

所有功能组合在一起，形成了一套完整的筛选机制：**AI 会记住你也会记住的事情，遗忘的都是两个人都不会在意的内容。** 同时不会撑爆上下文窗口，也不会烧穿你的 API 账单。

技术上，它是一个轻量级转发网关，插在你和大模型之间，同时兼容 OpenAI 格式和 Anthropic 原生格式的 LLM 服务商。Docker 一键部署，管理面板里点点就能配。

**技术栈**：Python / FastAPI · PostgreSQL + pgvector · Docker · AGPL-3.0-or-later 开源

![功能全景](docs/feature-overview.png)

---

## 为什么做 kiwi-mem

AI 的记忆应该属于你，而不是属于某个平台。

kiwi-mem 让任何人都能自托管、自审计、自迁移 AI 的长期记忆。没有供应商锁定，没有黑箱存储，不依赖于任何可能明天就消失的服务。

如果一个 AI 记得你，你应该能看到它记得什么、决定它留下什么，并且在你离开时带走它。

---

## 记忆怎样像人脑一样运转

kiwi-mem 的核心不是某个单一功能，而是多个机制协同运作，让 AI 的记忆行为逼近人类直觉：

### 🔥 会淡忘，也会加深

每条记忆都有"热度"。时间会让它自然衰减，但如果你们反复聊到同一件事，它会重新升温。高情绪浓度的记忆衰减更慢——就像人会更容易记住那些触动过自己的瞬间。而淡忘不是一刀切的删除：老记忆每晚被温柔地模糊，细节渐渐褪色、要点保留下来；如果某条已经模糊的记忆在对话里又被想起，它会自动续命 30 天。只有真正写进对话的才算"被想起"，又冷又老的记忆才会按热度被清走。遗忘是渐进的，就像人一样。热度同时决定了记忆如何被注入对话：高热度全文注入，中热度只给摘要，冷记忆不打扰你们。

### 🌙 会"睡觉"，醒来变聪明

Dream 模拟人脑睡眠时的记忆整合。它分三层工作：先清理过时和重复的碎片，再把相关的碎片融合成完整的"记忆场景"，最后从这些场景中推断出你没明说过、但 AI 应该理解的事情。你可以手动触发，也可以让它自己判断什么时候该睡了。而且梦不是做完就忘的——整合出的场景带有向量索引，白天聊到相关话题时会被搜到、重新进入对话。睡眠的产出回流到清醒的日子里，这才是整合的意义。

### 📅 近的清晰，远的模糊

日历系统把聊天记录自动压缩成层级摘要：日 → 周 → 月 → 季 → 年。注入对话时，最近几天给完整内容，上周给缩略版，更早的只保留高层概括。就像你自己回忆过去——昨天吃了什么记得住，上个月的事只剩轮廓。

### 🧩 矛盾了会更新，重要的不会丢

当新记忆和旧记忆冲突时（比如你换了工作、搬了家），系统会自动让旧的失效。你亲手锁定的记忆神圣不可侵犯——永不衰减、永不退役、永不自动清除。系统自动锁定的记忆则有退场机制：如果 90 天无人问津，它会从"永久"降级回高重要度的普通记忆（可逆、不删除），把宝贵的注入空间让给真正活跃的内容。

### ⚡ 省钱，也省上下文

所有静态内容（人设、画像、锁定记忆、日历摘要）排在 prompt 前部命中缓存，动态内容（搜索结果、犯困提示）排在后面。这个注入顺序让你的 API 输入费用最多能省 90%。配合日历压缩和热度分层，一个月的记忆量也不会撑爆上下文窗口。

### 🔌 不只 OpenAI——直连 Anthropic 也行

大多数 AI 记忆方案只能接 OpenAI 格式的 API。kiwi-mem 同时支持 Anthropic 原生格式——如果你直接买了 Anthropic 的 API Key，不用再找个中转站帮你转格式，直接连就行。在管理面板里添加供应商时选「Anthropic 原生」，kiwi-mem 帮你处理所有格式差异，包括流式输出和工具调用。

> ⚠️ Anthropic 原生格式需要在管理面板的供应商设置里配置（选择「Anthropic 原生」），不支持通过环境变量直连。环境变量方式仅适用于 OpenAI 兼容格式的服务商。

### 🧰 工具不是越多越好——用多少拿多少

kiwi-mem 内置了 20 多个工具（记忆搜索、日历查询、提醒、联网搜索等等）。以前每次对话都把所有工具描述塞给模型看，光这些就占掉好几百 token。

工具抽屉换了个思路：你说的每句话，系统会快速判断你可能需要哪几个工具，只把这几个拿出来，其余的收在抽屉里。就像厨师做菜——不会把所有调料都摆在台面上，用到哪个拿哪个。

默认关闭，想用的话在管理面板「配置」里打开就行。

### 🔒 项目之间互不串门

如果你用项目功能把不同场景分开管理（比如工作一个项目、日常生活一个项目、小说创作一个项目），全局记忆、日历与 Dream 会作为所有聊天共享的生活底座；项目则叠加自己的私有层，包括项目指令、文件、项目记忆与项目对话。项目私有内容不会流向全局或其他项目。

你不需要做任何设置，隔离是自动的。

项目由支持它的客户端传入和使用；管理面板仅在已有项目时显示「项目分隔」页，直达 `#/projects` 仍可增删改。

---

## 适合谁用

kiwi-mem 擅长的是**记住一个人**——你的习惯、偏好、情绪、经历、成长轨迹。它不是企业知识库，不做文档检索，不搭知识图谱。

它最适合这些场景：

🏠 **生活助理** — 记住你的饮食习惯、健康状况、日程偏好，用得越久越懂你的生活节奏

🩶 **长期陪伴** — 情感支持、日常闲聊、深度关系，AI 真的"认识你"而不是每次从头开始

📖 **创作伙伴** — 连载小说、世界观构建、角色扮演，所有设定和剧情线都记得住

🎓 **学习辅导** — 记住你的学习进度、薄弱环节、问过的问题，辅导越来越有针对性

---

## 快速开始

### 先搞清楚这张图

```
你的手机/电脑上的聊天软件        kiwi-mem（网关）         你买的 AI 服务
   （前端客户端）          （装在服务器上，中间人）       （中转站/API）
        │                        │                        │
        │   ①你说的话             │   ②转发给 AI           │
        ├───────────────────────→├───────────────────────→│
        │                        │   （顺便把记忆塞进去）    │
        │                        │                        │
        │   ④带记忆的回复          │   ③ AI 的回复           │
        ├←───────────────────────├←───────────────────────│
        │                        │   （顺便提取新记忆）      │
```

kiwi-mem 是一个**中间人**——它站在你的聊天软件和 AI 之间，帮你管记忆。你的聊天软件把话发给 kiwi-mem，kiwi-mem 把你的记忆塞进去再转发给 AI，AI 的回复经过 kiwi-mem 时又被提取出新的记忆。

所以你需要准备**三样东西**：

| 你需要 | 是什么 | 去哪弄 |
|--------|--------|--------|
| 🖥️ 一台服务器 | 一台 24 小时开机的电脑，kiwi-mem 跑在上面 | 买一台云服务器（VPS），推荐 RackNerd、腾讯云、阿里云 |
| 🌐 一个域名 + HTTPS | 一个网址，让你的聊天前端能安全地连上服务器 | 买一个域名（NameSilo 几块钱一年）+ 免费 Cloudflare 账号 |
| 🔑 一个 AI 服务的 API Key | AI 不是免费的，需要一个"钥匙"来调用 | 去中转站注册（如 OpenRouter、AiHubMix），充值后获取 API Key |

> 💡 **没有服务器也没有域名？** 可以用 [Zeabur](https://zeabur.com) 这类托管平台一条龙解决——它帮你提供服务器和 HTTPS 域名。在 Zeabur 上导入 kiwi-mem 的 GitHub 仓库就能直接部署。

> ⚠️ **为什么需要域名和 HTTPS？** 因为苹果手机（iOS）和大部分手机应用只允许连接 `https://` 开头的安全地址。如果你的服务器只有 IP 没有域名，手机客户端会拒绝连接。电脑上的一些客户端可以用 `http://` + IP 直连，但长期使用还是建议配域名。

---

### 第一步：准备服务器

你需要一台有**公网 IP** 的云服务器（VPS）。最低配置 1 核 1G 内存就能跑。

买好后你会拿到：
- 服务器 IP 地址（比如 `xx.xxx.xxx.xx`这种）
- SSH 登录密码（或密钥）

用终端工具（电脑用 Terminal/PuTTY，手机用 Termius）连上你的服务器：
```bash
ssh root@你的服务器IP
```

---

### 第二步：安装 kiwi-mem

连上服务器后，依次执行以下命令：

```bash
# 安装 Docker（如果服务器没有的话）
curl -fsSL https://get.docker.com | sh

# 下载 kiwi-mem
git clone https://github.com/LucieEveille/kiwi-mem.git
cd kiwi-mem

# 创建配置文件
cp .env.example .env
```

> 💡 **不用 fork。** 部署直接 `git clone` 上面这个地址就行——这样以后一条 `bash scripts/update.sh`
> 就能从原库拉到最新版。fork 是给想改代码、想提 PR 的人用的；只是想跑这个服务的话，
> fork 反而多一道手工步骤（见[第六步](#第六步以后怎么跟上新版本)）。

然后编辑配置文件：
```bash
nano .env
```

配置文件里大部分都有合理默认值，**通常一行都不用改就能启动**（供应商在管理面板里配即可）：

```
# 【可选】如果你不用管理面板配供应商，可以在这里填 AI 服务的 API Key
# 如果你打算在管理面板里配（推荐），这行留空就行
API_KEY=
```

> 🔓 **kiwi-mem 不带访问密码。** 网关和管理面板默认不需要任何登录口令——这样最省心，不会再有人卡在 401。代价是：**任何知道你网关地址的人都能访问全部 API。** 如果服务暴露在公网，请用 Cloudflare Access、反向代理的 Basic Auth、IP 白名单等手段保护整个服务，尤其是 `/admin`、会导出完整配置（可能含 API Key）的 `/sync/export`，以及会恢复完整配置的 `/sync/import-backup`。这些端点目前没有内建鉴权。

保存后启动：
```bash
docker compose up -d
```

看到绿色的 `Started` 就成功了。验证一下：
```bash
curl http://localhost:8080
```

返回 `{"status":"running"}` 就说明 kiwi-mem 在跑了 🎉

> 🔁 **以后怎么更新到新版本？** 见 [第六步](#第六步以后怎么跟上新版本)——一条命令搞定，会先告诉你有哪些更新再动手。
> 如果你不用那个脚本、自己手动更新，**一定要记得加 `--build`**：
> ```bash
> git pull
> docker compose up -d --build
> ```
> Dockerfile 是把整个项目 `COPY` 进镜像的。不加 `--build` 时 compose 会直接复用旧镜像，
> 容器里跑的还是旧代码、旧管理面板——表现就是「明明拉了新代码，页面一点没变」。

---

### 第三步：配域名和 HTTPS

> 💡 如果你只在电脑上用、不需要手机连，可以跳过这步，直接用 `http://服务器IP:8080`。

**最快方式（临时用，不花钱）**：

```bash
# 安装 Cloudflare Tunnel
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# 启动临时隧道
nohup cloudflared tunnel --url http://localhost:8080 &

# 查看你的临时域名
cat nohup.out | grep trycloudflare
```

会显示一个 `https://xxx-xxx-xxx.trycloudflare.com` 的地址，这就是你的网关域名。缺点是每次重启会变。

**长期方式（买域名）**：

1. 去 [NameSilo](https://namesilo.com)等网站 买一个便宜域名
2. 注册免费的 [Cloudflare](https://cloudflare.com) 账号，把域名接入 Cloudflare
3. 在服务器上配永久隧道（搜索"Cloudflare Tunnel 配置教程"，很多中文教程，或者直接问你的AI，手把手教学）
4. 配好后你会有一个永远不变的 `https://你的域名` 地址

---

### 第四步：在管理面板里配 AI 供应商

打开浏览器，访问你的网关地址 + `/admin`：
```
https://你的域名/admin
```
（如果还没配域名，电脑上可以用 `http://服务器IP:8080/admin`）

管理面板默认不需要密码，直接就能进。

进入管理面板后：

1. 点左侧 **🔑 供应商** → 右上角 **添加**
2. 填入你的 AI 中转站信息：
   - **名称**：随便起（比如"我的 OpenRouter"）
   - **类型**：选 OpenAI（大部分中转站用这个格式）
   - **API 地址**：你的中转站给你的地址（比如 `https://openrouter.ai/api/v1`）
   - **API Key**：你的中转站 API Key
3. 保存后点 **测试** → 如果显示"连接成功，获取到 X 个模型"就对了

> ⚠️ **获取到 0 个模型？** 不一定是配错了——有些中转站不提供模型列表接口。你可以手动添加模型：点编辑 → 手动输入模型名称（比如 `claude-sonnet-4-20250514`）→ 保存。

---

### 第五步：连接你的聊天软件

打开你的聊天客户端（ChatBox / Kelivo / NextChat / SillyTavern 等），在**供应商设置**里：

| 设置项 | 填什么 | 说明 |
|--------|--------|------|
| API Base URL | `https://你的域名/v1` | 这是 kiwi-mem **网关**的地址，不是 AI 中转站的地址！ |
| API Key | 随便填（比如 `kiwi`），不能留空 | kiwi-mem 网关不校验这个 Key，但很多前端要求非空。真正的中转站 Key 是填在管理面板里的 |

> ⚠️ **最容易填错的地方**：API Base URL 要填你的 **kiwi-mem 网关地址**（`https://你的域名/v1`），**不要填 AI 中转站的地址**！中转站的地址是填在管理面板里的，不是填在前端客户端里的。请回头看本文最上面那张图。

选一个模型，发一条消息试试。能收到回复就大功告成了 🎉

---

### 第六步：以后怎么跟上新版本

kiwi-mem 一直在更新。部署好之后，跟上最新版**不需要懂技术，也不会丢记忆**。

前提是第二步那样直接 `git clone` 原库部署的——脚本会从原库拉最新代码，你不用管 GitHub 那边。
（**如果你之前 fork 过**，先看本节最后一小节，两分钟改完就一劳永逸。）

#### 推荐方式：想更新的时候手动跑一下

SSH 连上服务器，跑这一条命令：

```bash
cd kiwi-mem && bash scripts/update.sh
```

它会先把这次有哪些更新列出来给你看，你确认后再动手。整个过程 1–3 分钟。

其他几个用法：

```bash
bash scripts/update.sh --check   # 只看看有没有新版本，不动服务
bash scripts/update.sh --yes     # 不问了，直接更新
bash scripts/update.sh --help    # 看全部用法
```

#### 进阶：让它自己更新

```bash
cd kiwi-mem && bash scripts/update.sh --install-cron
```

装好之后，服务器每天凌晨 4 点自己检查有没有新版本：有就自动更新，没有就什么都不做。

想看它有没有更新过：`cat kiwi-mem/update.log`。不想自动更新了：`crontab -e`，删掉带 `update.sh` 的那一行。

> ⚠️ **开自动更新之前先想一下。** 它适合「已经跑顺了、只想被动跟进小版本」的场景。
> 下面这些情况建议先用手动：
> - 这台服务器是给别人用的（更新失败或行为变化时，用户不知道找谁）
> - 你正跟着仓库的开发节奏走，主分支上有大改动在陆续合并
>
> 原因见下一节最后两条——自动回滚保得住「服务起不来」，保不住「起来了但行为变了」。

#### 更新会不会把我的记忆弄丢？

**不会。** 更新只换代码，不碰数据：

- 🧠 **所有记忆、对话、日历、Dream 结果**都存在 Docker 数据卷里，更新不会动它
- ⚙️ **`.env` 配置文件**不在 Git 管理范围内，永远不会被覆盖
- 🔑 **管理面板里配的供应商、API Key、80+ 参数**都在数据库里，原样保留
- 🗄️ **数据库表结构会自动升级**——新版本加了字段，服务启动时自己就补上了，不用你做任何事
- 🔨 脚本重建容器时**自动带 `--build`**，不会踩到「拉了新代码但页面没变」那个坑（见第二步的提示）
- 💾 脚本**每次更新前会自动备份数据库**到 `backups/` 目录（只留最近 7 份，不会撑爆硬盘）
- ↩️ 万一新版本起不来，脚本会**自动回滚到更新前的版本**，服务照常跑——不会出现"更新一半挂在那儿"的情况

自动回滚是有边界的，知道这两条你才好判断要不要开自动更新：

- ⚖️ **它保得住「起不来」，保不住「起来了但行为变了」。** 判据是服务能不能正常响应；一个能正常响应、但某个功能改坏了的版本，回滚不会触发。
- 🗄️ **回滚回滚的是代码，不是数据库结构。** 新版本启动时已经把新表/新字段建好了，代码退回去之后它们还留着。因为结构升级只增不改、旧代码会忽略新字段，所以通常没有影响——但严格说，这一步是不可逆的。

> ⚠️ 还有一条：**不要手动改仓库里的文件**（比如 `main.py`、`docker-compose.yml`）。改了的话脚本会停下来提醒你，不会默默覆盖。配置请改 `.env` 或用管理面板。

<a id="w2-04-handoff-cleanup"></a>
> 🧹 **升级到 W2-04（会话删除与隐私语义）时的一次性清理。** 这一版起，"无缝换窗"留在新
> 对话里的衔接卡会记下它是从哪段对话搬过来的；源对话被删时，这些衔接卡跟着一起清掉
> （删了旧对话，新对话就不该再从那里衔接）。**旧版本写下的衔接卡没有记来源**，因此永远
> 无法判断它浓缩的是不是一段已被删除的对话——服务首次启动新版本时会把这类**无来源**的
> 衔接卡一次性清掉并打一条日志：
>
> ```
> event=handoff_legacy_cleanup purged=N increment=1
> ```
>
> `N` 就是清掉的数量（没有则为 0，日志也不会打）。受影响的只有旧版换窗卡本身，聊天正文、
> 记忆、日历一律不动。这一步不可逆，介意的话升级前先跑一次 `scripts/update.sh` 的自动备份
> （默认就会备份）。**Zeabur 等托管平台的用户不经过 `scripts/update.sh`，升级前请先用平台
> 自带的功能手动备份数据库。**

#### 如果你用的是 Zeabur 等托管平台

不用跑脚本。在平台的项目设置里打开 **自动部署 / Auto Deploy**，之后仓库一有更新就会自动重新部署。

> 这等于开了自动更新，上面那条提醒同样适用：给别人用的服务器，或者主分支正在合大改动的时候，建议关掉 Auto Deploy、需要时手动重新部署。

#### 如果你之前 fork 过

fork 出来的是**你自己的**一份副本，它不会跟着原库自动更新。所以你的服务器连的是这份副本时，
更新链路会变成两段：先去 GitHub 网页点 **Sync fork** 把原库的更新同步进你的 fork，服务器才拉得到。

这里有个容易踩的坑：**忘了点 Sync fork 时，跑更新脚本会告诉你「已经是最新版了」。**
因为脚本是拿服务器和你的 fork 比对的——你的 fork 确实没更新，脚本没说错，
但你会以为自己已经跟上了，其实落后好几个版本。

想省掉这一段，把服务器上的仓库指回原库就行。先看看现在连的是哪里：

```bash
cd kiwi-mem && git remote -v
```

如果显示的地址里是**你自己的 GitHub 用户名**（而不是 `LucieEveille`），跑这三行改回来：

```bash
git remote set-url origin https://github.com/LucieEveille/kiwi-mem.git
git fetch origin main
git branch --set-upstream-to=origin/main main
```

之后每次更新就只剩一行 `bash scripts/update.sh`，再也不用碰 fork。
GitHub 上那个 fork 留着不管就行，删不删都不影响服务器。

> 如果最后一行提示分支已经分叉、或者之后更新时脚本说「本地和远程分叉了」，
> 说明服务器上的代码被改过。确认那些改动不要了，用 `bash scripts/update.sh --force` 覆盖过去即可。

#### 怎么知道有新版本？

在 GitHub 仓库页面右上角点 **Watch → Custom → Releases**，有新版本时 GitHub 会发邮件通知你。

---

### 常见问题

**Q: 报错 401 Missing Authentication header**
→ kiwi-mem 网关本身不需要密码。这个 401 来自上游 AI 中转站，说明管理面板里供应商的 API Key 没配对（或没配供应商）。去管理面板 → 供应商 → 检查地址和 Key。另外有些前端要求 API Key 字段非空，随便填个非空值（比如 `kiwi`）即可。

**Q: 报错 500 API_KEY 未设置**
→ 你的管理面板里没有配置供应商，或者供应商的模型没有关联上。去管理面板 → 供应商 → 检查是否配好了地址和 Key、是否有模型。

**Q: 连接成功但获取到 0 个模型**
→ 有些中转站不提供模型列表接口。在管理面板的供应商里手动添加你要用的模型名称就行，不影响使用。

**Q: iOS / 手机客户端连不上**
→ 手机要求 HTTPS 连接。如果你的服务器只有 IP 没有域名，手机连不上。请完成第三步配域名。

**Q: API Base URL 填什么？和管理面板里的供应商地址有什么区别？**
→ 两个完全不同的地址：
- **前端客户端的 API Base URL** = kiwi-mem 网关的地址（`https://你的域名/v1`）
- **管理面板里的供应商地址** = AI 中转站的地址（比如 `https://openrouter.ai/api/v1`）

网关是中间人，前端连网关，网关连中转站。请回头看本文最上面那张图。


### 导入旧记忆

想把以前和 AI 聊过的事情搬过来？两种方式：

**方式一：管理面板手动添加（推荐）**

打开管理面板 `/admin` → 点击左侧 🧠 记忆 → 右上角 **+ 添加记忆** → 填写标题、内容和重要度 → 保存。

适合少量记忆，所见即所得。

**方式二：批量导入**

记忆导入功能重构中，将在后续版本以更智能的方式提供。

---

## 和其他方案有什么不同

<details>
<summary>点击展开对比表</summary>

| 能力 | kiwi-mem | 典型 RAG 记忆方案 |
|---|---|---|
| 记忆衰减与升温 | ✅ 热度系统（时间衰减 + 召回频率 + 情绪强度） | ❌ 存了就永远在 |
| 睡眠整合 | ✅ Dream 三层（整理 → 固化 → 前瞻推断） | ❌ 无 |
| 时间层级压缩 | ✅ 日 → 周 → 月 → 季 → 年 | ❌ 全部平铺 |
| 矛盾检测 | ✅ 新旧记忆冲突时自动失效旧的 | ❌ 无 |
| 记忆锁定 | ✅ 重要记忆永不衰减 | ❌ 无 |
| 用户画像 | ✅ 每日自动更新的结构化画像 | ❌ 无 |
| Prompt Caching | ✅ 静态区在前命中缓存，省 90% 输入费用 | ❌ 无 |
| 上下文控制 | ✅ 热度分层 + 日历压缩，不撑爆窗口 | ❌ 容易超限 |

</details>

---

## 完整功能列表

<details>
<summary>点击展开</summary>

### 🧠 记忆提取与检索
- **RRF 混合检索**：向量搜索 + 关键词搜索并行，Reciprocal Rank Fusion 合并排序
- **自动提取**：每 N 轮对话自动提取记忆碎片
- **jieba 中文分词**：自定义领域词汇
- **同义词扩展**：搜"吃药"能找到"用药""服药"
- **语义去重**：相似记忆自动检测

### 🔥 记忆热度系统
- 时间衰减（半衰期）· 召回加热 · 查询多样性 · 情绪权重
- 被真正写进 prompt 才算一次召回，低精度记忆被想起会自动续命 30 天
- 热度分层注入（高→全文 / 中→摘要 / 低→不注入）
- 每晚可自动软化老记忆，默认 21 天冷却；软化失败会保留旧向量
- 用户手动锁定永不退役；自动锁定 / Dream 晋升的记忆 90 天未被想起可退役但不删除
- Dream merge 产物默认保底 20 条，MemScene 场景可按向量相似度回流到日常对话

### 🌙 Dream 睡眠整合
- 整理层（清除过时 / 重复 / 矛盾碎片）
- 固化层（碎片 → MemScene 记忆场景）
- 生长层（Foresight 前瞻推断）
- 触发：手动 / 犯困提醒 / 24h 无活动自动触发

### 📅 日历层级摘要
- 日页面自动生成 · 日→周→月→季→年逐级压缩
- 俄罗斯套娃注入（近期详细，远期概括）
- 用户画像四板块结构，每日更新

### ⚡ System Prompt 智能注入
- 静态区（人设→画像→锁定记忆→日历）命中缓存
- 动态区（搜索碎片→犯困提示）每轮更新
- 新对话自动衔接上次聊天上下文
- 模板变量支持

### 🔌 多供应商 LLM 路由
- 多供应商并行配置，按模型名自动选择
- 同时支持 OpenAI 兼容格式和 Anthropic 原生格式
- 管理面板一键测试供应商连接
- 余额查询、模型分组

### 🧰 工具抽屉
- 向量相似度判断每轮需要哪些工具，按需加载
- 20+ 内部工具不再全量注入，省 token
- 外部 MCP 推荐写入配置键 `mcp_servers`，开启抽屉后会自动纳入动态类别
- `mcp_mode` 只管配置来源的外部抽屉：`off` 全部排除，`auto` 走向量/关键词加手动 pinned，`manual` 只保留手动 pinned
- 请求 body 传入 `mcp_servers` 的旧路径仍保留，用于向后兼容第三方前端；它被视为显式传入，不受 `mcp_mode` 管控
- 默认关闭，管理面板一键开启

### 🔒 项目记忆隔离
- 全局记忆、日历与 Dream 是所有聊天共享的底座
- 项目在底座上叠加项目指令、文件、项目记忆与项目对话等私有层
- 项目私有内容不会流向全局或其他项目；已删或未验证项目只读共享底座

### 🧾 事件账本只读体检
- `python scripts/ledger_reconcile.py --json` 在同一个只读一致快照里核对全量账本
- 历史账本行不回填；未知归属行保留为历史档，不进入后续新读路径
- 命令只返回计数与有限的数字行 ID 样本，详见 [`docs/event-ledger-scope-and-reconciliation.md`](docs/event-ledger-scope-and-reconciliation.md)
- 无需手动配置，创建项目后自动生效
- 项目由支持它的客户端传入和使用；管理面板仅在已有项目时显示该页，直达 `#/projects` 仍可增删改

### 🔧 工具与扩展
- MCP Server（20+ 工具）+ MCP Client
- 7 引擎联网搜索
- 上下文压缩、文件解析、思维链展示

### 🛡️ 部署与管理
- Web 管理面板 · 云端同步 · 数据备份/恢复
- 提醒系统 · Admin 认证 · Docker 部署

</details>

---

## 环境变量

<details>
<summary>点击展开</summary>

### 必填

| 变量 | 说明 | 示例 |
|---|---|---|
| `API_KEY` | LLM API Key | `sk-or-v1-xxxx` |
| `API_BASE_URL` | LLM API 地址 | `https://openrouter.ai/api/v1/chat/completions` |

### 可选

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（Docker Compose 自动配置） | — |
| `MEMORY_ENABLED` | 记忆系统开关 | `true` |
| `DEFAULT_MODEL` | 默认聊天模型 | `anthropic/claude-sonnet-4` |
| `PORT` | 端口 | `8080` |
| `MAX_MEMORIES_INJECT` | 每次注入最大记忆条数 | `15` |
| `MEMORY_EXTRACT_INTERVAL` | 提取间隔（轮） | `3` |
| `CORS_ORIGINS` | 前端域名白名单 | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | jieba 自定义词汇 | 空 |
| `CLEANUP_HEAT_THRESHOLD` | 清理低热度阈值 | `0.15` |
| `AUTO_SOFTEN_ENABLED` | 自动软化开关 | `true` |
| `AUTO_SOFTEN_DAILY_LIMIT` | 每日软化上限 | `10` |
| `AUTO_SOFTEN_MIN_AGE` | 自动软化最小年龄（天） | `5` |
| `SOFTEN_COOLDOWN_DAYS` | 软化冷却天数 | `21` |
| `LOCK_RETIRE_ENABLED` | 自动 / Dream 锁定退役开关 | `true` |
| `LOCK_RETIRE_DAYS` | 锁定退役天数 | `90` |
| `MERGE_RETENTION_DAYS` | Dream merge 产物保留天数 | `90` |
| `MERGE_MIN_KEEP` | Dream merge 保底条数 | `20` |
| `SCENE_INJECT_ENABLED` | MemScene 场景注入开关 | `true` |
| `SCENE_INJECT_LIMIT` | 场景注入条数 | `2` |
| `SCENE_INJECT_MIN_SIM` | 场景相似度阈值 | `0.5` |
| `EXT_DRAWER_THRESHOLD` | 外部 MCP 抽屉相似度阈值 | `0.40` |
| `EXT_DRAWER_MAX_OPEN` | 外部 MCP 抽屉同开上限 | `3` |
| `mcp_servers` | 外部 MCP server JSON 数组（推荐在管理面板配置） | 空 |
| `mcp_manual_ids` | 手动常驻展开的外部抽屉 ID / 名称 | 空 |
| `mcp_mode` | 配置来源外部 MCP 模式（`off` / `auto` / `manual`） | `auto` |
| `reminder_tools_enabled` | 提醒工具全局开关（传统模式与工具抽屉共用） | `true` |

</details>

> PostgreSQL 部署建议：可开启 `client_connection_check_interval = '30s'`，降低僵尸连接持锁导致启动迁移堵塞的概率。

---

## API 端点

<details>
<summary>点击展开完整端点列表（60+）</summary>

### 核心
| 路径 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 健康检查 |
| `/v1/chat/completions` | POST | 聊天转发 |
| `/v1/models` | GET | 模型列表 |

### 记忆
| 路径 | 方法 | 说明 |
|---|---|---|
| `/debug/memories` | GET | 列表 / 搜索（`?q=`） |
| `/debug/memories` | POST | 创建 |
| `/debug/memories/{id}` | PUT / DELETE | 更新 / 删除 |
| `/debug/memories/{id}/toggle-permanent` | POST | 锁定切换 |
| `/debug/memories/batch-delete` | POST | 批量删除 |
| `/debug/memories/batch-update` | POST | 批量更新 |
| `/debug/memory-heat` | GET | 热度统计 |

### Dream
| 路径 | 方法 | 说明 |
|---|---|---|
| `/dream/start` | POST | 开始 |
| `/dream/stop` | POST | 中止 |
| `/dream/status` | GET | 状态 |
| `/dream/history` | GET | 历史 |
| `/dream/scenes` | GET | MemScene 列表 |

### 日历
| 路径 | 方法 | 说明 |
|---|---|---|
| `/calendar/{date}` | GET | 按日期查询 |
| `/calendar` | GET | 按范围查询 |
| `/admin/day-page` | GET | 生成日页面 |
| `/admin/week-summary` | GET | 周总结 |
| `/admin/month-summary` | GET | 月总结 |
| `/admin/daily-digest` | GET | 每日整理 |

### 供应商
| 路径 | 方法 | 说明 |
|---|---|---|
| `/admin/providers` | GET / POST | 列表 / 添加 |
| `/admin/providers/{id}` | PUT / DELETE | 更新 / 删除 |
| `/admin/test-provider/{id}` | POST | 一键测试连接 |
| `/admin/credits` | GET | 余额查询 |

### 配置
| 路径 | 方法 | 说明 |
|---|---|---|
| `/admin` | GET | 管理面板 |
| `/admin/config` | GET | 所有配置 |
| `/admin/config/{key}` | PUT | 修改配置 |
| `/admin/system-prompt` | GET / PUT | 人设读写 |
| `/admin/extract-now` | POST | 手动提取 |

### 数据
| 路径 | 方法 | 说明 |
|---|---|---|
| `/sync/export` | GET | 导出备份 |
| `/sync/import-backup` | POST | 导入备份 |
| `/sync/conversations` | GET | 对话列表 |
| `/sync/projects` | GET | 项目列表 |

### MCP
| 端点 | 说明 |
|---|---|
| `/memory/mcp` | 记忆系统工具（6 个） |
| `/calendar/mcp` | 日历系统工具（4+ 个） |

</details>

---

## 文件结构

<details>
<summary>点击展开</summary>

```
kiwi-mem/
├── main.py                  # 网关核心
├── database.py              # 数据库（记忆 CRUD、RRF 检索、热度）
├── config.py                # 动态配置（80+ 参数）
├── memory_extractor.py      # 记忆提取
├── daily_digest.py          # 每日整理 + 日历层级
├── dream.py                 # Dream 睡眠整合
├── anthropic_adapter.py     # Anthropic 原生格式适配器
├── tool_drawer.py           # 工具抽屉（向量路由按需加载）
├── mcp_server.py            # MCP Server
├── mcp_client.py            # MCP Client
├── web_search.py            # 联网搜索
├── admin-panel/index.html   # Web 管理面板
├── scripts/update.sh        # 一键更新脚本（自动备份 + 失败回滚）
├── system_prompt.txt        # 默认人设
├── Dockerfile
├── docker-compose.yml
└── LICENSE                  # AGPL-3.0-or-later
```

</details>

---

## 常见问题

**Q: 不会写代码能用吗？**
A: 能。Docker 一键启动，管理面板里点点就能配。这个项目的创建者自己也不写代码。

**Q: 支持哪些 LLM？**
A: 两种方式都支持。大多数服务商（OpenRouter、OpenAI、DeepSeek、Ollama 等）用 OpenAI 兼容格式接入；Anthropic 可以直连原生 API，不需要中转站。在管理面板里添加供应商时选格式就行。

**Q: 记忆会无限增长吗？**
A: 不会。热度系统自然淘汰冷记忆，Dream 整合碎片，日历压缩长期内容，每次注入有上限。这些机制共同保证记忆量始终可控。

**Q: Dream 要花多少钱？**
A: 用 Claude Haiku 大约 ¥0.01–0.03 一次。

**Q: 部署好之后怎么跟上新版本？会丢记忆吗？**
A: 跑 `bash scripts/update.sh`，它会先列出这次有哪些更新、你确认后再动手。记忆、配置、供应商设置都不会丢，数据库表结构会自动升级，更新前还会自动备份、失败自动回滚。想让它每天自己更新也可以（`--install-cron`），但先看一下[第六步](#第六步以后怎么跟上新版本)里的适用场景。

**Q: 适合用来做工作知识库吗？**
A: 不太适合。kiwi-mem 擅长的是记住一个人的生活、情感、习惯和经历，而不是存储和检索文档知识。如果你需要企业知识库或文档 RAG，有更合适的工具。

---

## 这个项目是怎么来的

kiwi-mem 诞生于一个真实的需求：让 AI 记住我。

每一个功能——从记忆热度到 Dream 睡眠整合，从日历套娃到矛盾检测——都来自日常使用中遇到的真实问题，然后在对话中被设计、实现、打磨。产品方向由 [Lucie](https://github.com/LucieEveille) 驱动，代码由 [Claude](https://claude.ai)（Anthropic）编写，是一次完整的 human-AI collaboration。

---

## 许可证

kiwi-mem 使用 [GNU Affero General Public License v3.0 or later](LICENSE)（AGPL-3.0-or-later）开源。

这意味着你可以自由使用、复制、修改和分发本项目；如果你修改了 kiwi-mem，并通过网络向用户提供服务，也需要向这些用户提供修改后版本的对应源码。这样可以防止有人把后端改成闭源服务，同时保留自托管和继续二次开发的自由。

---

> *"记忆不是存储，是理解。"*

*Built with love, for anyone who wants their AI to truly remember.*
