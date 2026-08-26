# CLAUDE.md — backend/app/templates/

Jinja2 HTML 报告模板（Task 17）。`app.services.reports` 用 `Environment(FileSystemLoader)` 加载，
PDF 渲染流程 = 模板渲染 HTML → xhtml2pdf `pisa.CreatePDF` → PDF 字节 → MinIO。

## 文件

- `reports/base.html.j2`：基础布局（内联 CSS + `{% block body %}` + 页脚生成时间）。
  中文字体引用 `WenQuanYi Zen Hei`（本机 `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`），
  xhtml2pdf 直接按家族名映射；字体缺失时回退默认字体（中文显示 tofu，但 PDF 仍有效）。
- `reports/validation.html.j2`：核验报告（评分/通过·警告·失败/耗时 + 15 条规则明细表）。
  变量来自 `_build_validation`：`report_id/score/passed/warning/failed/duration/created_at/rules[]`。
- `reports/data_list.html.j2`：数据列表（记录表格）。变量来自 `_build_data_list`：
  `items[]`（weld_id/registration_no/weld_name/source/machine/weld_method/material/quality/operator）+ `total`。
- `reports/generic.html.j2`：通用模板（analysis/annotation/features/test 复用）：
  `summary[]`（键值对）+ `sections[]`（`{heading, items:[{label, value}]}`），无 sections 显示占位。

## 坑/限制

- **autoescape 必须显式开启**：`app/services/reports.py` 的 Jinja `Environment(autoescape=True)`——
  `select_autoescape(["html","xml"])` 按**文件名结尾**匹配，`.j2` 模板匹配不到会返回 False，
  导致 `{{ weld_name }}` 等用户字段原样渲染（可注入 HTML/PDF）。改回 `select_autoescape` 前
  必须确认匹配 `.j2`。回归测试：`tests/test_reports.py::test_jinja_autoescape_escapes_user_fields`。
- 模板用 `{% extends "base.html.j2" %}`，文件名带 `.j2` 后缀（同 xhtml2pdf 兼容无冲突）。
- xhtml2pdf 只支持内联 CSS 2 子集：表格/边框/字体可用；flex/grid/定位等不生效，勿用。
- 变量取值一律在 `app/services/reports.py` 装配成 dict 再渲染，模板里不写复杂逻辑；autoescape
  对变量转义是刻意的（PDF 渲染 HTML 实体为字面字符，不会破坏表格/CSS）。
- 新增报告类型：加模板 + 在 `reports.py::_TEMPLATE_BY_TYPE` / `_BUILDERS` 注册。
