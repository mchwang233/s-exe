# create_proj

[中文](#中文) | [English](#english)

`create_proj` 是一个可独立分发的 Python 脚本，用于从内嵌或外部的
s-exe 验证模板快速创建 ASIC/验证项目。

`create_proj` is a standalone Python script that creates an ASIC/verification
project from either its embedded s-exe template or an external template.

## 中文

### 功能

- 默认使用脚本内嵌的 s-exe 模板，无需额外下载模板文件。
- 创建独立的 `asic/` 和 `verif/` 目录。
- 将模板中的 `my_*`、`MY_*` 和 `my-` 名称替换为项目前缀。
- 自动生成项目根目录的 `sourceme` 环境脚本。
- 可通过 `--src` 使用本地 s-exe 目录作为模板。
- Jinja2 为可选依赖；未安装时会使用内置的轻量渲染器。

### 环境要求

- Python 3
- 可选：Jinja2

脚本已经具有可执行权限时，可以直接运行。否则使用 `python3 create_proj`，
或先执行：

```bash
chmod +x create_proj
```

### 快速开始

在当前目录创建名为 `usb` 的项目：

```bash
./create_proj usb
```

生成的目录结构如下：

```text
usb/
├── asic/
├── sourceme
└── verif/
    └── ...
```

加载生成的环境配置：

```bash
source usb/sourceme
```

首次使用前，请根据本机环境修改 `usb/sourceme` 中的 `VCS_HOME`。然后可在
已配置好相关 EDA 工具的环境中运行：

```bash
sexe build
sexe run --case smoke
```

### 用法

```text
create_proj [-h] [--src SRC] [--out-dir OUT_DIR] [--prefix PREFIX]
            [--force]
            project
```

参数说明：

| 参数 | 说明 |
| --- | --- |
| `project` | 项目目录名，例如 `usb` 或 `acme_dma`。 |
| `--src SRC` | 使用指定的外部 s-exe 目录作为模板。默认使用内嵌模板。 |
| `--out-dir DIR` | 新项目的父目录。默认为当前目录。 |
| `--prefix PREFIX` | 替换模板中 `my_*` 名称的前缀。默认使用规范化后的项目名。 |
| `--force` | 删除并重新创建已存在的同名项目目录。请谨慎使用。 |
| `-h`, `--help` | 显示帮助。 |

示例：

```bash
# 在 /tmp/projects 下创建项目
./create_proj usb --out-dir /tmp/projects

# 使用外部模板
./create_proj usb --src /path/to/s-exe

# 项目名和模板前缀分别设置
./create_proj usb_controller --prefix usb

# 覆盖已经存在的目标目录
./create_proj usb --force
```

### 项目名规范化

项目名和前缀会转换为小写 snake_case：非字母数字字符会变为下划线，连续
下划线会被合并。如果名称以数字开头，则会自动添加 `p_`。

例如：

| 输入 | 生成的项目名 |
| --- | --- |
| `USB Controller` | `usb_controller` |
| `demo-v2` | `demo_v2` |
| `123-demo` | `p_123_demo` |

### 注意事项

- 如果目标目录已存在，脚本默认会退出，不会修改已有内容。
- `--force` 会递归删除整个同名目标目录，然后重新生成项目。
- 使用外部模板时，版本控制元数据、常见缓存、编辑器临时文件和仿真输出不会
  被复制。
- 生成的 `sourceme` 默认包含示例 VCS 安装路径，通常需要按实际环境修改。

## English

### Features

- Uses an embedded s-exe template by default, with no separate template download.
- Creates separate `asic/` and `verif/` directories.
- Rewrites `my_*`, `MY_*`, and `my-` names using the selected project prefix.
- Generates a root-level `sourceme` environment script.
- Accepts a local s-exe directory as a template through `--src`.
- Works without Jinja2 by falling back to a small built-in renderer.

### Requirements

- Python 3
- Optional: Jinja2

Run the script directly if it is executable. Otherwise, use
`python3 create_proj`, or make it executable first:

```bash
chmod +x create_proj
```

### Quick start

Create a project named `usb` in the current directory:

```bash
./create_proj usb
```

The generated layout is:

```text
usb/
├── asic/
├── sourceme
└── verif/
    └── ...
```

Load the generated environment:

```bash
source usb/sourceme
```

Before first use, update `VCS_HOME` in `usb/sourceme` for your local setup.
With the required EDA tools available, you can then run:

```bash
sexe build
sexe run --case smoke
```

### Usage

```text
create_proj [-h] [--src SRC] [--out-dir OUT_DIR] [--prefix PREFIX]
            [--force]
            project
```

| Argument | Description |
| --- | --- |
| `project` | Project directory name, such as `usb` or `acme_dma`. |
| `--src SRC` | Use an external s-exe directory as the template. The embedded template is the default. |
| `--out-dir DIR` | Parent directory for the generated project. Defaults to the current directory. |
| `--prefix PREFIX` | Prefix used to replace `my_*` names. Defaults to the sanitized project name. |
| `--force` | Delete and recreate an existing project directory. Use with care. |
| `-h`, `--help` | Show command help. |

Examples:

```bash
# Create the project under /tmp/projects
./create_proj usb --out-dir /tmp/projects

# Use an external template
./create_proj usb --src /path/to/s-exe

# Use a prefix different from the project name
./create_proj usb_controller --prefix usb

# Replace an existing target directory
./create_proj usb --force
```

### Name normalization

Project names and prefixes are converted to lowercase snake_case. Non-alphanumeric
characters become underscores, repeated underscores are collapsed, and names that
start with a number receive a `p_` prefix.

| Input | Generated project name |
| --- | --- |
| `USB Controller` | `usb_controller` |
| `demo-v2` | `demo_v2` |
| `123-demo` | `p_123_demo` |

### Notes

- If the target directory exists, the script exits without modifying it by default.
- `--force` recursively removes the entire target directory before regenerating it.
- When using an external template, version-control metadata, common caches, editor
  swap files, and simulation output are excluded.
- The generated `sourceme` contains an example VCS installation path that normally
  needs to be updated for the local environment.
