# CLAUDE.md — backend/app/templates/reports/

Jinja2 报告模板（Task 17）。加载与渲染机制、变量契约、autoescape 坑见上级 `../CLAUDE.md`。

## 文件

- `base.html.j2`：基础布局（内联 CSS + `{% block body %}` + 页脚生成时间），中文字体 `WenQuanYi Zen Hei`。
- `validation.html.j2`：核验报告（评分 + 15 条规则明细），变量来自 `_build_validation`。
- `data_list.html.j2`：数据列表报告，变量来自 `_build_data_list`。
- `generic.html.j2`：通用模板（analysis/annotation/features/test 复用），`summary[]` + `sections[]`。

## 坑/限制

- 模板名带 `.j2` 后缀；新增报告类型需在 `app/services/reports.py` 的 `_TEMPLATE_BY_TYPE` / `_BUILDERS` 注册。
- xhtml2pdf 仅支持内联 CSS 2 子集（flex/grid 不生效）；autoescape 必须显式开启（见上级坑）。
