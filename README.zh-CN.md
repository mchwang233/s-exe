# ssv - 可复制的 UVM 验证环境参数传递核心

[English](README.md) | [简体中文](README.zh-CN.md)

**核心思路（4 步）**：

1. 在 `.cfg` 中编写参数的唯一事实来源（例如 `top.cfg`、`sub_agent.cfg`）。`cfg2sv.py` 会在同一目录生成对应的 `cfg/<class>.sv`（类继承自 `ssv_object`），并生成 `cfg/ssv_cfg_pkg.sv` 和 `cfg/all.cmd`。
2. 只编译一次：默认 simv 位于 `sim/output/baseline/simv`（运行 `sexe build`）。
3. 运行用例时，Python 读取 `cases/<case>.cmd`，提取其中的 `ssv_cfg:` 行，使用 Python `fnmatch` **展开 glob**，然后写入 `sim/<variant>/run/<case>/cfg.info`；同时将 simv 进程的当前工作目录切换到该用例运行目录（即 `cfg.info` 所在目录）。
4. simv 启动后，测试在 `build_phase` 中调用 `ssv_object::apply_overrides_in_cwd(root_cfg)`，内部以相对路径打开 `"cfg.info"`，再由 `dispatch_path` 分发。**SV 端不读取 `cases/*.cmd`，不读取 plusarg 或环境变量，也不处理 glob；它只消费当前工作目录下的 `cfg.info`。**

**目录结构**：

```text
ssv/
├── cfg/                    # .cfg 源文件 + 自动生成的 .sv / ssv_cfg_pkg.sv / all.cmd
│   ├── top.cfg             # 根配置（同目录自动生成 top.sv）
│   ├── sub_agent.cfg       # 子类配置（同目录自动生成 sub_agent.sv）
│   ├── lib/                # 可选子目录（通过 @ 引入）
│   │   └── scoreboard.cfg  # .sv 也生成在同一目录
│   ├── ssv_cfg_pkg.sv      # 自动生成，由 filelist 引用
│   └── all.cmd             # 自动生成的配置转储（供 Python 展开 glob）
├── cases/                  # .cmd 文件（编译期及运行期指令）
├── tools/                  # cfg2sv.py、run_case.py 和 bin/sexe
├── tb/
│   ├── utiles/ssv/         # 可复制的最小核心（ssv_object.sv + ssv_pkg.sv）
│   ├── env/                # 示例 env/agent
│   ├── tests/              # 示例测试
│   ├── filelist.f          # VCS filelist（引用 cfg/ssv_cfg_pkg.sv）
│   └── tb_top.sv           # testbench 顶层
├── sim/                    # 仿真产物和编译参数
│   ├── build/              # 编译配置 .cmd；添加文件即可新增构建变体
│   │   ├── baseline.cmd    # → sim/output/baseline/simv
│   │   └── kdb.cmd         # → sim/output/kdb/simv
│   └── output/<variant>/
│       ├── simv            # 可执行文件
│       ├── build/          # VCS -Mdir / -Mlib
│       ├── logs/vcs.log    # 编译日志
│       └── run/<case>/
│           ├── cfg.info    # 从用例 .cmd 提取并展开后的配置
│           └── sim.log     # 用例仿真日志
└── （没有 gen/；cfg 和 sv 位于同一目录，便于整体复制到其他项目）
```

**`.cfg` 文件语法**：

每个 `.cfg` 文件最多定义一个顶层类。字段使用 `::` 分隔类型和名称（不用
`:`，因此不会与 `bit [7:0]` 之类的 packed 位宽冲突）。值末尾的分号或
逗号均可省略。

```text
# 或 // 注释；字符串之外也支持行尾注释

@./sub_agent.cfg                  # 引入一个独立 cfg 类，只能写在顶层

ssv_root_cfg {                    # <类名> { ... }
  int unsigned :: NUM_AGENTS = 2; # <类型> :: <字段名> [= <SV 字面量>]
  bit [7:0]    :: MASK       = 'hff;
  string       :: ENV_NAME   = "demo #1";  # 引号内的 # 是字符串内容
  real         :: PERIOD_NS;               # 省略值时默认为 0.0
  int[]        :: COUNTERS   = '{1, 2, 3}; # 动态数组
  string[$]    :: NAMES;                   # 队列

  sub_agent_cfg agent_a {          # <类名> <实例名> { ... }
    int    :: AGENT_ID = 0;         # 覆盖被引用类中的字段
    string :: NAME     = "agent_a";
  }
}
```

语法摘要：

```text
cfg-file       := { include } class-block
include        := "@" path                         # 只能位于 class 块之外
class-block    := class-name "{" { field | sub-object } "}"
sub-object     := class-name instance-name "{" { field } "}"
field          := type "::" field-name [ "=" value ] [ ";" | "," ]
```

- 标量类型支持 `int`、`int unsigned`/`uint`、`bit`、`logic`、`byte`、
  `shortint`、`longint`、`real`、`string`，以及 packed 类型
  `bit [...]` / `logic [...]`。类型后添加 `[]` 表示动态数组，添加 `[$]`
  表示队列。
- 未填写值时，整数类类型默认值为 `0`，`bit`/`logic` 为 `1'b0`，
  `real` 为 `0.0`，`string` 为 `""`，数组和队列使用 SystemVerilog 的空
  assignment pattern。
- 每个文件只能包含一个顶层类。不支持嵌套类定义；包含两个名称的块表示
  子对象实例。被引用类可以来自扫描到的其他 `.cfg` 文件或 `@` 引入文件。
- 类和子对象也可写成单行形式，字段之间用分号分隔，例如：
  `sub_agent_cfg { int :: ID = 0; bit :: ENABLE = 1'b1; }`。
- 双引号字符串之外，`#` 和 `//` 可用于整行或行尾注释；字符串中的这些
  字符会被原样保留。
- `@` 支持绝对路径或相对于当前 `.cfg` 的路径，并展开 `$VAR` 和
  `${VAR}`。可以嵌套引入，但循环引入会报错；引入的类保持独立，不会自动
  合并字段。

**`.cmd` 文件语法**：

```text
vlogan:        <args>        # 编译参数（仅 build，可选）
vcs:           <args>        # 编译参数（仅 build，可选）
                              # `vcs: -l <file>` 指定编译日志；vcs 的 cwd 是 simv 所在目录
simv:          <arg>         # 运行参数，每行一个
                              # 选择测试类的唯一方式，例如：
                              # simv: +UVM_TESTNAME=my_long_test
                              # `simv: -l <file>` 指定仿真日志；cwd 是用例运行目录
                              # cases/<x>.cmd 中为用例参数
                              # sim/build/<v>.cmd 中为变体默认参数，先于用例参数追加
                              # 对 -l 而言，后出现的用例参数会覆盖默认值
binary:        <path>        # 选择 simv，路径相对于 sim/（可选）
ssv_cfg:       <path> = <val>
                              # 运行期配置覆盖；Python 将其写入 cfg.info
                              # 精确路径保持不变；包含 * / ? / [ 时用 fnmatch 展开
break:         <time>        # 调试停止点；start 或 0 表示立即停止，否则为 +kdb_stop=<time>
precomp:       <shell cmd>   # 编译前钩子（cwd=项目根目录，bash）；失败则终止编译
presim:        <shell cmd>   # 仿真前钩子（cwd=用例运行目录）；失败则不启动 simv
postsim:       <shell cmd>   # 仿真后钩子；失败只记录警告，最终仍采用 simv 返回码
seed:          <int|random>  # UVM 随机种子；省略或 random 时生成 1..2^31-1 的随机值
                              # 映射为 +UVM_SEED=<int>
inc:           <path>        # 引入另一个 .cmd；路径相对于项目根目录
                              # 内容插入当前位置；支持嵌套，循环引入会报错
```

`.cmd` 通用规则：

- 文件按行解析，格式为 `指令: 内容`。忽略首尾空白及空内容，不支持续行；
  未知行按注释处理。
- 双引号字符串之外，`#` 和 `//` 可用于整行或行尾注释。`inc:` 文件中的
  指令等效于写在引入位置。
- 重复的 `vlogan:`、`vcs:`、`simv:`、`ssv_cfg:` 和钩子指令会按出现
  顺序追加；`binary:` 和 `seed:` 使用最后一个值。
- `simv:` 内容按空白拆分，不进行 shell 引号解析；启动前会展开环境变量。
  钩子内容则由 `/bin/bash` 原样执行。
- `ssv_cfg:` 使用第一个 `=` 分隔路径和值，并移除可选的
  `ssv_root_cfg.` 前缀。精确路径直接输出；`*`、`?`、`[...]` 模式会基于
  `cfg/all.cmd` 进行区分大小写的展开。`[0]` 之类的数字数组下标不会被
  当作 glob。没有匹配项的 glob 会被保留，以便 SV 端报告未知字段警告。

**Glob 语法**（用于 `ssv_cfg:` 路径，由 Python `fnmatch` 展开）：

```text
ssv_cfg: agent_*.NAME        = "x"     # 匹配 agent_a.NAME / agent_b.NAME
ssv_cfg: *.ADDR_WIDTH        = 64      # 匹配所有以 .ADDR_WIDTH 结尾的字段
ssv_cfg: agent_?.AD?R_WIDT?  = ...     # ? 匹配单个字符
```

**`@` 引入语法**（用于 `.cfg`，提供类似 cpp 的独立配置加载）：

```text
@<path>            # 加载指定 .cfg，其顶层类会注册到全局
                   # 当前 cfg 不会自动合并被引入文件中的字段
                   # @ 只能出现在顶层 class 块之外
                   # 支持嵌套 @；循环引用会报错
                   # 被引入文件中的类可按普通方式实例化

路径解析：
    - 以 / 开头 → 绝对路径
    - 其他路径 → 相对于当前 .cfg 文件所在目录
    - 支持 ${VAR} 和 $VAR 环境变量展开
    - 展开后仍存在 $ 表示环境变量未定义，会报错

示例：
    # cfg/shared/sub_agent.cfg
    sub_agent_cfg { int :: AGENT_ID = 0; bit :: IS_ACTIVE = 1'b1; ... }

    # cfg/top.cfg
    @./shared/sub_agent.cfg

    ssv_root_cfg {
      ...
      sub_agent_cfg agent_a { int :: AGENT_ID = 7; }
    }
```

**动态数组和队列**（在 `.cfg` 中声明为 `int[]` / `int[$]`）：

```text
# 动态数组：用 FIELD.size 修改长度，用 FIELD[N] 写入第 N 个元素
ssv_cfg: MY_DYN_ARR.size = 4
ssv_cfg: MY_DYN_ARR[0]   = 10
ssv_cfg: MY_DYN_ARR[3]   = 40   # 长度不足时自动扩展

# 队列：.cmd 中的每一条 `=` 都执行一次 push_back（追加到 .cfg 默认值之后）
ssv_cfg: MY_QUEUE        = 100
ssv_cfg: MY_QUEUE        = 200

# string 动态数组和队列的用法相同
ssv_cfg: NAMES.size      = 2
ssv_cfg: NAMES[0]        = "alice"
ssv_cfg: NAMES_Q         = "carol"
```

详情参见 `cases/arrays_demo.cmd` 以及 `cfg/top.cfg` 中的 5 个示例字段。

**最简单的 4 步用法**（从项目根目录运行 `sexe`；内部通过 `__file__` 定位项目，所以也可从其他目录调用）：

```bash
sexe build                                       # 构建 baseline simv
sexe run --case smoke                            # 使用 baseline 运行 smoke
sexe run --case smoke --variant kdb              # 使用 kdb 变体；首次运行时自动构建
sexe regress --cases smoke override_demo glob_demo hooks_demo
sexe list-builds                                 # 列出 sim/build/ 下的构建变体
sexe --help                                      # 查看所有子命令和说明
```

**修改 `cfg/` 后**：运行 `sexe build` 重新生成并编译 simv。构建配置内置了 `precomp: python3 tools/cfg2sv.py`，每次构建都会将 `cfg/*.cfg` 编译为同目录下的 `cfg/*.sv`，并重新生成 `cfg/all.cmd`，无需手动运行 `cfg2sv.py`。

**添加构建变体**：在 `sim/build/` 下新增一个 `.cmd` 文件（包含 `vlogan:`、`vcs:`、`precomp:` 等行），文件名即变体名，然后运行 `sexe build --variant <new_name>`。可直接参考现有的 `baseline.cmd` 和 `kdb.cmd`。

**钩子示例**（`cases/hooks_demo.cmd`）：

```bash
precomp: echo "[precomp] regen some code" && python3 tools/regen.py
presim:  echo "[presim] setup marker" > presim_marker.txt
postsim: cat presim_marker.txt && rm presim_marker.txt
postsim: echo "[postsim] fatal=$(grep -c UVM_FATAL sim.log)"
```

---

**复制到其他项目**：

```bash
# 1. 复制核心
cp -r <ssv>/tb/utiles/ssv/ <new>/tb/utiles/ssv/

# 2. 复制脚本
cp <ssv>/tools/{cfg2sv,run_case}.py <new>/tools/

# 3. 添加到 filelist：
#      +incdir+tb/utiles/ssv
#      tb/utiles/ssv/ssv_pkg.sv
#      +incdir+cfg
#      cfg/ssv_cfg_pkg.sv

# 4. 复制包含 precomp 的构建配置
cp <ssv>/sim/build/baseline.cmd <new>/sim/build/baseline.cmd

# 5. 运行
sexe build
sexe run --case <yourcase>

# cfg/*.cfg 和生成的 cfg/*.sv 成对位于同一目录；请复制完整目录树。
# 通过 @ 引入的子目录（例如 cfg/lib/）也应一起复制。
```

---

**已知限制和说明**：

- EDA 工具链：`VCS_HOME=/workspace/eda/synopsys/vcs/W-2024.09`、`UVM_HOME=$VCS_HOME/etc/uvm-1.2`、`LM_LICENSE_FILE=/workspace/eda/synopsys/scl2025.03-sp2/Synopsys.lic`。
- VCS W-2024 + UVM 1.2 在不带 `-kdb` 时，运行时调度器会卡在 `uvm.uvm_sched.pre_reset`，因此 `baseline.cmd` 和 `kdb.cmd` 都包含 `-kdb`。
- `run_case.py` 会将 simv 的 cwd 设为用例运行目录；VCS 使用绝对的 `argv[0]` 查找 `simv.daidir`，因此 cwd 不影响该查找。
- `vcs` 的 cwd 是 `sim/<variant>/`，所以 `vcs: -l vcs.log` 会将日志放在 simv 旁边。`tb/filelist.f` 中的路径使用 `$PROJ_ROOT`，不依赖 cwd。
- SV 的 `substr(start, end)` 两端都包含；比较前缀时应使用 `substr(0, prefix.len()-1)`。
- 数值字段覆盖支持十进制数、`0`、`1`、`1'b0`、`1'b1`；其他字面量作为 cfg 默认值写入。
- packed vector 数组和标量通过 `ssv_ato_packed`（`tools/cfg2sv.py` + `ssv_object.sv`）赋值，不依赖 UVM `*_hext` 宏。
- interface 和 virtual interface：占位符位于 `tb/tb_top.sv`，请按项目需要替换。
- **入口命令是 `tools/bin/sexe` 中的 `sexe`**；执行 `source sourceme` 后可从任意目录运行，无需 Makefile。
- **不要添加 `-debug_access+all`**：VCS W-2024 的 cbug 栈标注器会调用 `cbug-gdb-64/bin/gdb`，当前环境中 gdb 返回 127 并导致 simv 卡住。只使用 `-kdb` 即可避免 UVM 1.2 的 `pre_reset` 卡死，并支持 `+kdb_stop=<time>` 调试断点。
