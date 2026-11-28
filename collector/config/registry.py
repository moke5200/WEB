#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源注册表（Python 版，零依赖、可写注释）。

增删源：改下面的 SOURCES 列表 + 在 sources/ 下加/删一个文件。
enabled=False 时不跑，代码留着方便随时开关。

字段说明：
  id                 源编号（a01…云端 / b29…带登录态）
  file               sources/ 下的文件名
  name               中文名（页面/日志用）
  category           分类（页面分区用）
  freq               频率标记，调度器据此判断本轮跑不跑：
                     30m / 2h / 3h / 6h / 12h / 1d / weekly-fri / on-demand
  runs_on            cloud（GitHub Actions）| local（本机，需 CDP/登录态）
  needs_login        是否需要 cookie/secret
  cross_source_dedup 是否参与跨源判重（同类软件站要开）
  raw_lang           默认语言，en 的会自动翻成中文
  output             output：001.md 表示写进 linux.do 001.md 格式；json 表示只进每日页
  enabled            开关
  note               备注
"""

SOURCES = [
    # ---------- 已迁移 ----------
    dict(id="a01", file="a01_linuxdo_cloud.py", name="linux.do 云资源版",
         category="云资源", freq="6h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="001.md", enabled=True,
         note="Cloudflare 429 自动走 Jina 中转；标签含夸克/百度才收，按网盘链接 ID 去重"),

    # ---------- 待迁移（先留位） ----------
    dict(id="a02", file="a02_linuxdo_welfare.py", name="linux.do 福利版",
         category="福利", freq="3h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="只采集不进 001.md；真好的强相关主动推，其余普通列表"),

    dict(id="a03", file="a03_smzdm.py", name="什么值得买",
         category="好价", freq="30m", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="不带 Cookie，从列表页 Nuxt 数据抠"),

    dict(id="a04", file="a04_sspai.py", name="少数派",
         category="资讯", freq="3h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a05", file="a05_apprcn.py", name="反斗软件",
         category="软件", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=True, raw_lang="zh", output="json", enabled=True,
         note="与 a07/a08 跨源去重"),

    dict(id="a06", file="a06_github_trending.py", name="GitHub Trending",
         category="开源", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="en", output="json", enabled=True),

    dict(id="a07", file="a07_xiaozhong.py", name="小众软件",
         category="软件", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=True, raw_lang="zh", output="json", enabled=True),

    dict(id="a08", file="a08_iplaysoft.py", name="异次元",
         category="软件", freq="2h", runs_on="cloud", needs_login=False,
         cross_source_dedup=True, raw_lang="zh", output="json", enabled=True),

    dict(id="a09", file="a09_nodeseek.py", name="NodeSeek",
         category="羊毛", freq="2h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="重点盯免费云电脑/VPS"),

    dict(id="a10", file="a10_v2ex.py", name="V2EX 推广",
         category="独立开发", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a11", file="a11_aihot.py", name="aihot.news",
         category="AI 额度", freq="12h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a12", file="a12_auc.py", name="AgentUseCases",
         category="Agent 案例", freq="12h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="en", output="json", enabled=True),

    dict(id="a15", file="a15_hackernews.py", name="HackerNews",
         category="英文资讯", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="en", output="json", enabled=True,
         note="先过滤纯名人捧场/情绪灌水"),

    dict(id="a16", file="a16_simon.py", name="Simon Willison",
         category="英文资讯", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="en", output="json", enabled=True),

    dict(id="a18", file="a18_epic.py", name="Epic 喜加一",
         category="免费游戏", freq="weekly-fri", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="每周五一次；每款附 B 站搜索链接"),

    dict(id="a19", file="a19_bili_subtitle.py", name="B站字幕工具模块",
         category="工具", freq="on-demand", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=False,
         note="底层模块，供 a20 和私人 Skill 调用"),

    dict(id="a20", file="a20_bili_up.py", name="B站指定 UP 主投稿",
         category="视频", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a21", file="a21_zhihu_hot.py", name="知乎热榜",
         category="资讯", freq="6h", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a24", file="a24_ai_quota.py", name="AI 平台免费额度（长期）",
         category="AI 额度", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),

    dict(id="a26", file="a26_youtube_rss.py", name="YouTube 精选博主 RSS",
         category="视频", freq="1d", runs_on="cloud", needs_login=False,
         cross_source_dedup=False, raw_lang="en", output="json", enabled=True,
         note="免 Key，抓 videos.xml"),

    dict(id="b29", file="b29_ruike.py", name="瑞客论坛",
         category="论坛", freq="1d", runs_on="local", needs_login=True,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="需 RUIKE_COOKIE secret"),

    dict(id="b35", file="b35_x_useful.py", name="X 主号（有用组）",
         category="X", freq="12h", runs_on="local", needs_login=True,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True,
         note="本机跑，复用现有 _x_to_md_v3.py"),

    dict(id="b37", file="b37_xhs_douyin.py", name="小红书/抖音热榜",
         category="热榜", freq="1d", runs_on="local", needs_login=True,
         cross_source_dedup=False, raw_lang="zh", output="json", enabled=True),
]


def by_id(sid):
    for s in SOURCES:
        if s["id"] == sid:
            return s
    return None


def enabled():
    return [s for s in SOURCES if s.get("enabled")]