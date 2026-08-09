# BD 网红底库模块

为 kol-finder 项目扩展的 BD 网红管理模块：支持 BD 底库表格、爆款/转化分析、韩文邮件生成、视频回链追踪、商品效果数据导入、内容 DNA 提取。

## 文件说明

| 文件 | 作用 |
|------|------|
| `bd_database.py` | BD 网红数据层（本地 SQLite + Supabase 双实现） |
| `youtube_analyzer.py` | YouTube Data API 封装：视频统计、评论抓取、爆款/转化分析 |
| `ai_email_generator.py` | AI 邮件/框架生成（OpenAI / Gemini / DashScope） |
| `product_importer.py` | CSV/Excel 商品数据导入与校验 |
| `app_demo.py` | 独立 Streamlit Demo，可直接运行 |
| `requirements.txt` | 依赖 |

## 快速体验 Demo

```bash
cd kol_bd_module
pip3 install -r requirements.txt
streamlit run app_demo.py
```

默认使用本地 SQLite，**示例数据为空**。需要演示数据时设置环境变量：

```bash
SEED_SAMPLE_DATA=1 streamlit run app_demo.py
```

## 接入 kol-finder 的步骤

### 1. 复制模块文件

把以下文件复制到 `kol-finder` 目录：

```
kol_bd_module/bd_database.py      -> kol-finder/bd_database.py
kol_bd_module/youtube_analyzer.py -> kol-finder/youtube_analyzer.py
kol_bd_module/ai_email_generator.py -> kol-finder/ai_email_generator.py
kol_bd_module/product_importer.py -> kol-finder/product_importer.py
```

### 2. 数据库迁移

在 Supabase 执行以下 SQL：

```sql
CREATE TABLE IF NOT EXISTS bd_influencers (
  id BIGSERIAL PRIMARY KEY,
  channel_id TEXT UNIQUE NOT NULL,
  channel_name TEXT DEFAULT '',
  channel_url TEXT DEFAULT '',
  category TEXT DEFAULT '',
  recruiter TEXT DEFAULT '',
  subscribers BIGINT DEFAULT 0,
  status TEXT DEFAULT '已引入',
  notes TEXT DEFAULT '',
  product_link TEXT DEFAULT '',
  ctr REAL,
  conversion_rate REAL,
  gmv REAL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3. 在 kol-finder/app.py 新增 Tab

参考 `app_demo.py` 里的 `render_bd_table`、`render_video_tracker`、`render_product_import` 等函数，在 `kol-finder/app.py` 新增一个 Tab：

```python
tab_search, tab_database, tab_bd, tab_import, tab_settings = st.tabs([
    "🔎 搜索挖掘", "📁 网红库", "🎯 BD 底库", "📥 批量导入", "⚙️ 筛选设置"
])
```

### 4. 与现有网红库打通

当用户在「网红库」把网红状态改为「已引入」时，调用：

```python
from bd_database import get_bd_db

bd_db = get_bd_db(use_supabase=True, supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)
bd_db.add({
    "channel_id": channel["channel_id"],
    "channel_name": channel["channel_name"],
    "channel_url": channel["channel_url"],
    "subscribers": channel["subscribers"],
    "category": channel.get("category", ""),
    "recruiter": channel.get("discovered_by", ""),
    "status": "已引入",
})
```

### 5. API Key 配置

在侧边栏增加：

- **YouTube Data API Key**：用于爆款/转化分析、视频追踪
- **AI Provider**：openai / gemini / dashscope
- **对应 API Key**：用于生成韩文邮件

### 6. 依赖更新

在 `kol-finder/requirements.txt` 里确认包含：

```
requests>=2.28.0
pandas>=1.5.0
openpyxl>=3.0.0
supabase>=2.0.0
```

## 设计决策

- **数据库**：独立 `bd_influencers` 表，通过 `channel_id` 与现有 `influencers` 表关联。
- **评论区转化分析**：走 YouTube Data API `commentThreads`，每 100 条评论 1 unit 配额，适合云端部署。
- **AI 邮件**：优先推荐 OpenAI `gpt-4o-mini`（韩语最自然），也支持 Gemini 免费层和 DashScope（千问）。
- **脚本形式**：给网红的是「拍摄框架」（创作方向 + 必须包含元素 + 参考话术），不是逐字稿。

## 后续可扩展

- 爆款/转化分析结果持久化到数据库
- 邮件发送状态追踪（已发送 / 已回复 / 已合作）
- 商品效果数据可视化图表
- 多人协作权限（RLS）
