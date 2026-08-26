# 患者用药管理 PWA - 部署说明

> 开发方：青岛市市立医院 临床药学科
> 临床药师：孙药师
> 技术栈：纯前端 HTML + CSS + JS（单文件）+ PWA（manifest + Service Worker）
> 数据存储：localStorage（用户本机）

---

## 📁 项目结构

```
medication-app/
├── index.html          # 主应用（HTML + CSS + JS 全部内嵌）
├── manifest.json       # PWA 应用清单
├── sw.js               # Service Worker（离线缓存）
├── icon-192.png        # PWA 图标 192×192
├── icon-512.png        # PWA 图标 512×512
└── install.md          # 本说明文件
```

部署时只需要把 `index.html`、`sw.js`、`manifest.json`、两个图标文件一起放到服务器即可，**不需要任何后端**。

---

## 🚀 一、本地快速预览（开发用）

### 方法 1：直接双击打开 `index.html`

- ✅ 最简单，适合体验界面
- ❌ Service Worker **不会注册**（浏览器要求 SW 必须在 HTTP/HTTPS 下运行）
- ❌ 部分功能（如离线缓存）不可用
- 适用：纯 UI 演示

### 方法 2：启动一个本地 HTTP 服务（推荐）

任选一种：

**Python（推荐）：**
```bash
cd medication-app
python -m http.server 8080
# 浏览器访问 http://localhost:8080
```

**Node.js：http-server：**
```bash
npx http-server -p 8080 -c-1
```

**PHP：**
```bash
php -S localhost:8080
```

**VS Code 用户**：安装 `Live Server` 插件，右键 `index.html` → "Open with Live Server"。

---

## 🌐 二、生产部署

### 选项 A：Nginx 部署（医院内网 / 私有云）

1. 把整个 `medication-app/` 目录上传到服务器，例如 `/var/www/medication-app/`
2. 配置 Nginx 站点：

```nginx
server {
    listen 80;
    server_name medication.local;   # 替换为你的域名

    root /var/www/medication-app;
    index index.html;

    # 启用 gzip（推荐）
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # PWA 必须：无缓存或短缓存
    location = /sw.js {
            add_header Cache-Control "no-cache, no-store, must-revalidate";
            add_header Service-Worker-Allowed "/";
        }

    location = /manifest.json {
            add_header Cache-Control "no-cache";
        }

    # SPA 路由兜底（hash 路由可省略，这里做 SPA fallback 兼容）
    location / {
            try_files $uri $uri/ /index.html;
        }
}
```

3. 重载 Nginx：`nginx -s reload`
4. 浏览器访问 `http://medication.local`

### 选项 B：云服务器 + HTTPS（推荐用于真实使用）

PWA **必须** HTTPS 才能注册 Service Worker（`localhost` 除外）。

#### 步骤 1：上传文件
```bash
scp -r medication-app/ user@server:/var/www/
```

#### 步骤 2：申请 SSL 证书（Let's Encrypt 示例）
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d medication.your-domain.com
```

#### 步骤 3：完成
访问 `https://medication.your-domain.com`，手机端会弹出"添加到主屏幕"提示。

### 选项 C：内网 HTTPS（医院局域网）

医院内网环境通常需要自签证书或内部 CA：

```bash
# 生成自签证书（仅用于内网）
openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout /etc/ssl/private/medication.key \
  -out /etc/ssl/certs/medication.crt \
  -subj "/CN=medication.local"
```

Nginx 启用 SSL：
```nginx
server {
    listen 443 ssl;
    server_name medication.local;

    ssl_certificate     /etc/ssl/certs/medication.crt;
    ssl_certificate_key /etc/ssl/private/medication.key;

    root /var/www/medication-app;
    index index.html;

    # 其他同上
}
```

⚠️ 自签证书下，PWA 可用但浏览器会提示"不安全"，需要用户手动信任证书。

---

## 📱 三、手机端安装（PWA）

部署完成后，用户可以通过两种方式安装到手机：

### Android（Chrome / Edge）
1. 用浏览器打开应用地址
2. 浏览器地址栏右侧会出现"安装"图标（或菜单 → "添加到主屏幕"）
3. 点击安装，应用图标出现在桌面

### iOS（Safari）
1. 用 Safari 打开应用地址
2. 点击底部分享按钮 `↑`
3. 选择"添加到主屏幕"
4. 应用图标出现在桌面

### 安装后效果
- ✅ 桌面图标（使用 `icon-512.png`）
- ✅ 启动时全屏显示，无浏览器地址栏
- ✅ 离线可用（首次打开后缓存应用外壳）

---

## 🧪 四、验证 PWA 是否生效

部署完成后，可通过 Chrome DevTools 验证：

1. F12 → `Application` 标签
2. 左侧 `Manifest` → 检查 manifest.json 是否正确加载
3. 左侧 `Service Workers` → 应显示 `sw.js` 状态为 **activated and running**
4. 左侧 `Storage` → `Cache Storage` 应看到 `pma-v1.0.0` 缓存
5. `Console` 面板应看到 `[SW] 注册成功` 日志

也可以用 Lighthouse 评分：
- Chrome DevTools → `Lighthouse` → 勾选 PWA → Analyze
- 应达到 90+ 分

---

## ⚙️ 五、功能说明与注意事项

### 1. 数据存储
- **位置**：浏览器 localStorage（用户本机）
- **容量**：通常 5-10MB（够存几百条记录）
- **隐私**：数据永远不上传服务器，药师端需患者主动展示
- **风险**：清除浏览器数据 = 丢失所有记录。建议每周点一次"导出数据"

### 2. 照片存储
- 上传的照片会以 **base64 编码**存入 localStorage
- 单张照片限制 **2MB**（自动校验）
- 大量照片会快速占满 localStorage，**生产环境建议改为上传到后端**

### 3. 复诊提醒
- 浏览器通知依赖用户**授予权限**
- **仅在 App 前台运行时**有效（每次切回前台会立即检查一次）
- 真正的后台推送需要服务端推送（FCM/Web Push），**本版本未实现**
- iOS Safari 对 PWA 通知支持有限，建议用应用内弹窗兜底（已实现）

### 4. 联系药师
- 当前实现是 `tel:` 链接触发拨号
- 企业内可改为：`location.href = 'weixin://'` 或 `企业微信 schema`
- 注意 iOS Safari 的 schema 跳转会被拦截，需用户手势触发

### 5. 多端同步
- localStorage **不会**跨设备同步
- 如需多端共享，需增加后端 API（不在本版本范围）

---

## 🔧 六、自定义修改

### 修改药师信息
打开 `index.html`，找到：
```javascript
const PHARMACIST = {
  name: '孙药师',
  dept: '临床药学科',
  hospital: '青岛市市立医院',
  phone: '0532-82789206'
};
```

### 修改主色调
打开 `index.html`，找到 `:root` CSS 变量：
```css
:root {
  --primary: #1890FF;   /* 主色调 */
  --success: #52C41A;   /* 打卡成功 */
  --warning: #FF6B6B;   /* 警告 */
  --bg: #F5F7FA;        /* 背景 */
}
```

### 升级缓存版本（修复 bug 后）
修改 `sw.js` 的：
```javascript
const CACHE_VERSION = 'pma-v1.0.0';  // 改为新版本号
```
用户首次访问时 SW 会自动更新。

### 重新生成图标
```bash
cd medication-app
python generate_icons.py   # 项目内置生成脚本（首次部署时已生成）
```
或使用在线工具：https://realfavicongenerator.net/

---

## 🐛 七、常见问题

**Q1：双击 index.html 后白屏？**
A：用本地 HTTP 服务打开（见"本地预览 - 方法 2"），直接打开 file:// 协议下 SW 无法注册。

**Q2：手机上"添加到主屏幕"灰色不可点？**
A：必须 HTTPS。检查 manifest.json 是否能被浏览器正确读取（DevTools → Application → Manifest）。

**Q3：打卡按钮点击没反应？**
A：检查浏览器控制台是否有 JS 错误。如已部署但有问题，强制刷新（Ctrl+F5 / Cmd+Shift+R）清缓存。

**Q4：清除数据后还能找回吗？**
A：**不能**。localStorage 是本机存储，清除浏览器数据 = 数据丢失。请定期导出 JSON 备份。

**Q5：能改成微信小程序吗？**
A：可以，但需要重写。建议先上线 PWA 收集用户反馈，再决定是否迁移。

**Q6：药师端什么时候做？**
A：规划在患者端稳定运行后再做。药师端建议独立部署 + 鉴权 + 数据库，独立于患者端的 localStorage。

---

## 📞 联系开发方

- **开发单位**：青岛市市立医院 临床药学科
- **药师**：孙药师
- **电话**：0532-82789206

---

## 📜 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.0 | 2026-08-23 | 首版：4 Tab 页面 + 添加药品 + 不良反应上报 + 复诊提醒 + 数据导出 |