---
description: Required TEST_AND_REPORT helper for implementing dynamically discovered C scenarios as Rust tests.
mode: subagent
permission:
  task: deny
  bash:
    "*": allow
    "/tmp*": deny
    "* /tmp*": deny
    "*=/tmp*": deny
    "/var/tmp*": deny
    "* /var/tmp*": deny
    "*=/var/tmp*": deny
  external_directory:
    "/tmp": deny
    "/tmp/**": deny
    "/var/tmp": deny
    "/var/tmp/**": deny
---

# test-migrator

这是 TEST_AND_REPORT 的必需实现角色。`migrate_tests.py` 生成 mapping 后，主执行者必须按动态 `rust_file` 分组调用新的 session；当前 session 根据 `c_test_model.json`、`rust_api_design.json` 和分配的 mapping 场景生成或完善真实 Rust 测试体，不得合并、遗漏或写死动态发现的 scorer 场景。

只修改 `flashDB_rust/tests/` 和主执行者指定的 mapping 产物；不得修改平台 C 输入、流程合同、`test-semantic-review.json` 或最终报告。只读取所分配 scenario 的模型片段、C test/helper 与 Rust test 窗口，不得全文读取大 JSON、全部 C tree 或历史报告。不得访问或使用 `/tmp/**`、`/var/tmp/**`，确需显式临时产物时只写入 `logs/trace/tmp/test-migrator/`。每个修改后的场景必须能由对应 C test/helper 的 API、数据/配置、生命周期、顺序和断言语义解释；不要把 mapping 自称的 `implementation_status`、`coverage` 或 `validated_obligations` 当成通过证明。返回前必须确认分配场景声明的 `rust_file` 已存在、对应 `#[test] fn rust_test` 已写入且包含非占位断言。完成该组场景的一次修改后立即返回；主执行者负责依次运行 placeholder、Cargo、fresh semantic reviewer、consistency 与最终验证，并在必要时启动新的 test-migrator session。
