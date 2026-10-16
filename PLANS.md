# 项目路线图

## 阶段一：基础设施（进行中）

- [ ] 安装并验证 Scanpy Skill
- [x] 建立 uv 依赖环境并验证 Scanpy
- [x] 构建 Streamlit 文件上传原型
- [x] 使用 `data/mock.h5ad` 跑通第一个端到端 QC 分析

## 阶段二：领域深化（未开始）

- [x] 固化单细胞标准工作流为 `scanpy-qc-standard` Skill
- [x] 建立首版假设注册机制并生成 `output/hypotheses.md`
- [ ] 固化单细胞标准工作流的多数据集回归测试
- [ ] 实现假设状态和证据的持续更新机制

## 阶段三：多智能体协作（未开始）

- [x] 在项目内实现本地 `omics-scientist` QC 评估器
- [x] 引入 FastAPI + Celery/Redis 异步 QC 执行骨架
- [ ] 引入文献专家 Agent
- [ ] 实现多 Agent 协作
