# 阶段03：构建C模型

## 执行内容

1. 读取 flashdb-migration SKILL.md 中 BUILD_C_MODEL 规则。
2. 运行 build_c_model.py，基于 input_manifest.json 构建C项目模型。
3. 仅记录事实，不做 Rust API 决策。

## 模型结果

- c_project_model.json：项目文件分类和依赖关系
- c_api_model.json：51个公共C函数、结构体、typedef、枚举和宏定义
- c_test_model.json：23个注册测试函数及其标准场景集合

## 状态

- C模型已构建完成，准备进入 DESIGN_RUST_API。
