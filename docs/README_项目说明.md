# 智安工坊——AI 安全开发协作平台

## 1. 项目名称

智安工坊——AI 安全开发协作平台

英文标识：Zhian Workshop / CodeGuard

## 2. 项目背景与解决的问题

大学生在课程作业、实验项目和毕业设计中，经常会把 API Key、数据库密码、Token、邮箱和手机号直接写入代码。项目可以运行，并不代表代码已经安全；一旦代码上传到 GitHub、Gitee 或公开网盘，敏感信息就可能随着提交历史长期保留。

智安工坊把“提交前检查”做成一个适合学生和教师使用的本地 Web 工作台。用户可以粘贴代码或上传 ZIP 项目，系统会定位疑似风险代码行，给出风险等级和置信度，并提供人工复核、AI 解释、修复示例、扫描历史对比和 PDF 审计报告。

## 3. 核心功能

1. 支持 Python、Java、C/C++、JavaScript/TypeScript 和常见配置文件。
2. 支持文本粘贴和 ZIP 项目上传。
3. 识别 API Key、Access Key / Secret Key、数据库账号密码、JWT Token、邮箱、手机号和疑似高熵凭据。
4. 根据规则信号、上下文、文件类型和凭据特征进行风险评分，分为严重、高、中、低四级。
5. 高亮风险代码行，展示文件名、行号、风险类型、证据和置信度。
6. 支持待确认、已确认、误报、已修复和忽略本次等人工复核状态。
7. 调用 DeepSeek 生成中文修复建议和正确示例；调用前只发送脱敏上下文，不自动修改源码。
8. 提供项目级整改计划，额度不足或接口不可用时使用内置建议。
9. 分析 requirements.txt、package.json、pom.xml 等依赖清单，提示版本范围过宽或需要人工核查的项目。
10. 对包含 `.git` 的 ZIP 读取提交次数、作者数量和近期提交，作为开发过程证据提示。
11. 保存本次运行期间的扫描历史，并支持前后风险数量和安全评分对比。
12. 导出适合课程作业、毕业设计和项目归档的 PDF 审计报告。

## 4. 技术栈

- 编程语言：Python 3.12、HTML5、CSS3、JavaScript ES2020+
- 后端框架：Flask 3.x
- 前端：原生 HTML/CSS/JavaScript，无独立前端框架
- 报告生成：ReportLab
- 环境配置：python-dotenv
- 测试：pytest
- AI 模型：DeepSeek Chat API
- 数据库：当前版本不使用数据库，扫描结果和历史保存在后端进程内存中

## 5. 项目目录结构

```text
智安工坊_AIWEB版/
├─ app/
│  ├─ main.py                 Flask 路由、上传和扫描接口
│  ├─ scanner.py              CodeGuard 混合检测和风险评分引擎
│  ├─ insights.py             依赖清单、Git 证据和项目洞察
│  ├─ llm.py                  DeepSeek 调用、脱敏和内置回退
│  ├─ reports.py              PDF 审计报告生成
│  ├─ templates/index.html    网页结构
│  └─ static/                 页面样式和交互脚本
├─ data/demo_project.zip      演示项目
├─ tests/                     自动化测试
├─ docs/                      项目材料和技术文档
├─ requirements.txt           Python 依赖
├─ .env.example               环境变量模板
├─ run.py                     启动入口
└─ README.md                  项目总说明
```

## 6. 安装依赖

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 7. 环境变量配置

复制 `.env.example` 为 `.env`，填写自己的 DeepSeek API Key：

```text
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=0
```

真实 Key 只保存在本机 `.env`，不能提交到 GitHub，也不要放入 README、截图、演示数据或 PDF。

## 8. 启动项目

```powershell
python run.py
```

浏览器打开：`http://127.0.0.1:5000/`

当前项目没有独立前端服务器，也没有数据库服务器；Flask 会同时提供网页和后端 API。

## 9. 测试账号及使用说明

当前版本没有登录功能，因此没有测试账号和密码。打开网页即可使用。

推荐演示流程：

1. 点击“粘贴代码”，输入文件名和演示代码，点击“开始检测”。
2. 点击右侧风险清单，查看风险代码位置、行号、风险等级和置信度。
3. 先查看内置修复建议，再点击“使用 DeepSeek 优化建议”。
4. 修改代码后重新扫描，使用扫描历史比较整改前后的风险数量和安全评分。
5. 点击“导出 PDF 报告”，保存审计结果。
6. 也可以选择“上传 ZIP”，使用 `data/demo_project.zip` 演示多文件项目扫描。

## 10. AI 功能实现方式

本地检测引擎先识别风险，DeepSeek 不负责直接扫描原始项目。用户点击 AI 功能后，系统只把文件名、行号、风险类别和已经脱敏的代码行发送给 DeepSeek，请模型生成中文解释、修复建议和示例代码。

系统不会把真实密钥直接发送给模型，也不会自动改写用户源码。如果 Key 未配置、网络不稳定或额度不足，系统会自动返回内置建议，保证本地检测和基本演示仍然可用。

## 11. 开发与原创性说明

本目录是面向 AI WEB 网页开发挑战赛的开发版本，基于团队原创 CodeGuard 初始版本建立。后续升级功能、测试和文档均在本目录中持续完成，并通过 Git 保留真实开发记录。项目不承诺替代正式安全审计，检测结果需要人工复核。
