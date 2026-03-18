# Emby Manager - Emby 注册管理系统

<p align="center">
  <img src="https://img.shields.io/badge/Docker-支持-blue?style=for-the-badge&logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/版本-v1.0.0-orange?style=for-the-badge" alt="Version">
</p>

基于 [guowanghushifu/emby-register-service](https://github.com/guowanghushifu/emby-register-service) 二次开发，在保留原版全部功能的基础上，新增了数据大盘、用户管理、多渠道推送通知和 Telegram Bot 远程控制。

> 📖 [English Version](README_EN.md)

---

## ✨ 功能特性

### 原版功能（完整保留）
- 🎟️ **Token 生成与 HMAC 签名验证** - 安全的注册链接机制
- 📝 **用户自助注册** - 从模板用户复制权限，无需手动配置
- 🔐 **管理员登录后台** - 密码支持明文或哈希存储

### 新增功能
- 📊 **数据大盘** — 实时在线播放、注册趋势图表（30秒自动刷新）
- 🎟️ **Token 增强** — 支持有效期（7天/30天/永久）、批量生成（最多50个）、备注
- 👥 **用户管理** — 查看所有注册用户，批量续期、锁定/解锁，一键处理到期账号
- 🔔 **多渠道推送** — 支持 Telegram、企业微信、钉钉、Server酱、飞书
- 📅 **定时报告** — 日报/周报/月报自动推送
- 🤖 **Telegram Bot** — 通过 Bot 远程查询状态、续期、锁定用户
- 🔒 **安全增强** — CSRF 保护、服务端 Session、密码哈希、防暴力破解

---

## 📋 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- Emby 服务器 4.7.0+

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/jialin4567/emby-register-enhanced.git
cd emby-register-enhanced

# 2. 复制并编辑配置文件
cp docker-compose.example.yml docker-compose.yml
# 编辑 docker-compose.yml，填写你的配置（见下方详细说明）

# 3. 启动服务
docker compose up -d

# 4. 查看日志
docker compose logs -f
```

浏览器访问 `http://你的IP:18080`，输入管理员密码登录。

### 方式二：Docker Run（快速测试）

```bash
docker run -d \
  --name emby-manager \
  -p 18080:5000 \
  -v $(pwd)/data:/app/data \
  -e FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  -e ADMIN_PASSWORD="your-admin-password" \
  -e EMBY_SERVER_URL="http://your-emby-server:8096" \
  -e EMBY_API_KEY="your-emby-api-key" \
  -e COPY_FROM_USER_ID="template-user-id" \
  -e PUBLIC_ACCESS_URL="http://your-domain:18080" \
  --restart unless-stopped \
  jialin4567/emby-register-enhanced:latest
```

### 方式三：从源码构建

```bash
git clone https://github.com/jialin4567/emby-register-enhanced.git
cd emby-register-enhanced
docker build -t emby-register-enhanced .
docker compose up -d
```

---

## ⚙️ 详细配置指南

### 第一步：生成 SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

将输出结果填入 `FLASK_SECRET_KEY`。

### 第二步：（推荐）对管理员密码进行哈希处理

`ADMIN_PASSWORD` 支持两种方式：直接填明文（简单但不推荐），或填哈希值（推荐）。

使用以下命令生成哈希：

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('你的密码'))"
```

输出示例：`pbkdf2:sha256:260000$xxx...`，以 `pbkdf2:` 开头，代码会自动识别并使用哈希对比。即使环境变量泄露，攻击者也无法反推出明文密码。

### 第三步：获取必填参数

#### 获取 EMBY_API_KEY

1. 登录 Emby 控制台（`http://你的Emby地址:8096`）
2. 进入 **设置 → 高级 → API 密钥**
3. 点击 **+** 按钮创建新密钥
4. 输入应用名称（如 `EmbyManager`），点击确认
5. 复制生成的密钥（一长串字符）

#### 获取 COPY_FROM_USER_ID

1. 在 Emby 中创建一个专用模板用户（**不要给管理权限！**）
2. 配置好该用户的媒体库权限、转码权限等
3. 进入 Emby 控制台 → 用户管理
4. 点击模板用户，查看浏览器地址栏
5. 复制 `userId=` 后面的字符串（例如：`a22935174ac24711aa54f84999999`）

**示例 URL：**
```
https://emby.your-domain.com:8920/web/index.html#!/users/user?userId=a22935174ac24711aa54f84999999
```

其中 `a22935174ac24711aa54f84999999` 就是 `COPY_FROM_USER_ID`。

### 第四步：完整的 docker-compose.yml 示例

```yaml
services:
  emby-manager:
    image: jialin4567/emby-register-enhanced:latest  # 使用预构建镜像
    # build: .  # 或从源码构建（二选一）
    container_name: emby-manager
    ports:
      - "18080:5000"  # 主机端口:容器端口
    volumes:
      - ./data:/app/data  # 数据持久化目录
    environment:
      # ========== 必填项 ==========
      - FLASK_SECRET_KEY=your-32-char-secret-key-here-xxxx
      - ADMIN_PASSWORD=your-admin-password-or-hash
      - EMBY_SERVER_URL=http://192.168.1.100:8096
      - EMBY_API_KEY=your-emby-api-key-from-console
      - COPY_FROM_USER_ID=template-user-id-from-url
      - PUBLIC_ACCESS_URL=http://your-domain.com:18080
      
      # ========== 可选配置 ==========
      
      # Cloudflare 加速地址（给国内用户使用）
      # - EMBY_SERVER_URL_CLOUDFLARE=https://emby-cf.your-domain.com
      
      # Telegram Bot 配置
      # - TG_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxyz
      # - TG_ADMIN_CHAT_ID=123456789
      
      # 企业微信推送
      # - WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
      
      # 钉钉推送
      # - DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
      # - DINGTALK_SECRET=SECxxx  # 如果启用了加签
      
      # Server酱推送
      # - SERVERCHAN_KEY=SCTxxx
      
      # 飞书推送
      # - FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
      
      # 定时报告（daily=日报, weekly=周报, monthly=月报，可组合）
      # - REPORT_SCHEDULE=daily,weekly,monthly
      # - REPORT_HOUR=8  # 每天几点推送，默认8点
      
    restart: unless-stopped
```

---

## 🤖 Telegram Bot 配置

### 创建 Bot

1. 在 Telegram 搜索 **@BotFather**
2. 发送 `/newbot` 创建新机器人
3. 按提示设置：
   - 机器人名称（显示名称）
   - 机器人用户名（必须以 bot 结尾，如 `MyEmbyBot`）
4. 保存返回的 **Bot Token**（格式：`123456789:ABCdefGHIjklMNOpqrSTUvwxyz`）

### 获取 Chat ID

1. 搜索 **@userinfobot**
2. 点击 **Start**，机器人会返回你的 Chat ID
3. 或者将 Bot 加入群组，发送一条消息，然后访问：
   ```
   https://api.telegram.org/bot<你的BotToken>/getUpdates
   ```
   查看返回的 JSON 中的 `chat.id`

### Bot 指令列表

Bot 仅响应 `TG_ADMIN_CHAT_ID` 配置的管理员，其他用户发送指令无效。

| 指令 | 说明 |
|------|------|
| `/start` 或 `/help` | 显示帮助信息 |
| `/status` | 服务器概览（在线人数、总用户数、到期用户数等） |
| `/online` | 当前在线播放列表 |
| `/users` | 所有用户列表（最近30个） |
| `/expiring` | 3天内到期用户 |
| `/renew <用户名> <天数>` | 续期，如 `/renew alice 30` |
| `/lock <用户名>` | 锁定用户（禁用 Emby 账号） |
| `/unlock <用户名>` | 解锁用户（启用 Emby 账号） |
| `/lockexpired` | 一键锁定所有到期用户 |
| `/report` | 立即发送日报 |

---

## 📊 界面预览

登录后自动进入**数据大盘**，左侧侧边栏切换各功能页面：

- **📊 数据大盘** — 实时播放流、注册趋势图、媒体类型分布、在线用户列表
- **🎟️ Token管理** — 生成/复制/删除注册链接，支持批量生成和备注
- **👥 用户管理** — 查看所有注册用户，批量续期、锁定/解锁，一键处理到期账号
- **🔔 推送通知** — 查看各渠道状态、手动触发推送、Bot 指令参考

---

## 💾 数据备份

所有数据都存储在 `./data` 目录，只需备份此目录即可：

```bash
# 备份
tar czvf emby-manager-backup-$(date +%Y%m%d).tar.gz ./data

# 恢复
tar xzvf emby-manager-backup-20240312.tar.gz
docker compose restart
```

---

## ❓ 常见问题

### Q: 无法访问管理后台？

**A:** 检查以下几点：
- 端口 18080 是否被其他程序占用
- 防火墙是否放行 18080 端口（`sudo ufw allow 18080`）
- Docker 容器是否正常运行（`docker ps | grep emby-manager`）
- 查看日志（`docker compose logs -f`）

### Q: Token 链接提示"无效、已被篡改或已过期"？

**A:** 
- 检查 `PUBLIC_ACCESS_URL` 配置是否正确，必须与浏览器访问地址完全一致（包括端口）
- 如果用了反向代理（Nginx），确保 `PUBLIC_ACCESS_URL` 是公网访问地址
- Token 是否已过期（在 Token 管理页面查看）

### Q: Telegram Bot 不响应指令？

**A:**
- 确认 `TG_BOT_TOKEN` 和 `TG_ADMIN_CHAT_ID` 配置正确
- Bot 只响应配置的管理员 Chat ID，其他用户发送指令会被忽略
- 重启容器后生效（`docker compose restart`）

### Q: 推送通知不生效？

**A:**
- 在管理后台的"推送通知"页面手动测试各渠道
- 检查 Webhook 地址是否正确
- 查看日志输出（`docker compose logs -f`）

### Q: 如何更新到最新版本？

**A:**
```bash
cd emby-register-enhanced
docker compose pull
docker compose up -d
```

### Q: 忘记管理员密码怎么办？

**A:** 修改 `docker-compose.yml` 中的 `ADMIN_PASSWORD`，然后重启容器：
```bash
docker compose restart
```

---

## 📝 更新日志

### v1.0.0 (2024-03-12)

**✨ 新功能**
- 数据大盘 - 实时监控播放状态、注册趋势图表
- 用户管理系统 - 支持批量续期、锁定/解锁、到期处理
- Token 增强 - 支持有效期、批量生成、备注
- 多渠道推送 - Telegram、企业微信、钉钉、Server酱、飞书
- 定时报告 - 日报/周报/月报自动推送
- Telegram Bot - 远程管理指令

**🔒 安全增强**
- CSRF 保护
- 服务端 Session（文件系统存储）
- 密码哈希支持（pbkdf2/scrypt/bcrypt）
- 防暴力破解（IP 限流）
- 安全响应头

**🎨 UI 改进**
- 全新深色主题设计
- 响应式布局，支持移动端
- Bootstrap 5 + Bootstrap Icons

---

## 🙏 致谢

本项目基于 [guowanghushifu/emby-register-service](https://github.com/guowanghushifu/emby-register-service) 开发，感谢原作者的开源贡献。

---

## 📄 License

MIT License - 详见 [LICENSE](LICENSE) 文件
