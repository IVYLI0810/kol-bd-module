# YTS 网红管理系统

AliExpress 韩国网红营销团队共享系统，数据存**钉钉宜搭**（全生命周期：挖掘 → 邮件 → 活动履约 → 下单/收货/拍摄 → 审核 → 闭环）。

## 文件说明

| 文件 | 作用 |
|------|------|
| `yts_main_app.py` | 管理站主程序（首页看板 / 挖掘 / 活动履约 / 数据分析） |
| `yts_review_app.py` | 审核站（审核同学专用，独立部署） |
| `yts_theme.py` | 裸粉极简主题 + 卡片表格 HTML 组件（含 iframe 跳转脚本） |
| `yts_yida_store.py` | 业务层：把宜搭记录映射成网红对象，封装所有状态流转写操作 |
| `yida_bd_database.py` | 宜搭数据层（aliding SDK，分页全量读取 + 增改） |
| `yts_store.py` | 本地 JSON 兜底数据层（无宜搭凭证时演示用，接口同上） |
| `app_demo.py` | 入口接力文件（Cloud 主站入口名固定，exec 执行 `yts_main_app.py`） |
| `app_review.py` | 入口接力文件（审核站入口，exec 执行 `yts_review_app.py`） |

## 本地运行

```bash
pip3 install -r requirements.txt
streamlit run yts_main_app.py        # 管理站
streamlit run yts_review_app.py      # 审核站
```

凭证按优先级自动选择：

1. `st.secrets` / 环境变量 `YIDA_APP_KEY`、`YIDA_APP_SECRET`（Cloud 用 Secrets 配置）
2. 同目录 `yida_config_local.py`（本地开发，不入 git）
3. 都没有 → 自动降级为本地 JSON 演示数据

## Streamlit Cloud 部署

- 主站：入口文件固定 `app_demo.py`（平台不允许改名，故用 exec 接力）
- 审核站：同仓库另建一个 App，入口同样 `app_review.py` 接力
- Secrets 配置：`YIDA_APP_KEY`、`YIDA_APP_SECRET`（钉钉开放平台应用凭证）

## 设计约定

- 活动模型：一个网红 × 一个活动 = 一条宜搭记录（复合键 upsert）
- 挖掘人身份门：活动履约进入前必选「我是谁」，名字写入 URL 参数 `rec`（iframe 跳转刷新不丢）
- 审核记录只增不减；审核站独立 App + 独立 Secrets
- 给网红的视频脚本只给框架（创作方向 + 必须包含元素 + 参考话术），不写逐字稿
