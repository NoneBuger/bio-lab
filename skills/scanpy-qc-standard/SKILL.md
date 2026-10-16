# scanpy-qc-standard

## 触发条件

当用户上传 `.h5ad` 文件并提到“质控”或“QC”时触发。

## 输入契约

- 输入：可读取的 AnnData `.h5ad` 文件。
- 基因名从 `adata.var_names` 获取；使用大小写不敏感的 `MT-` 前缀识别线粒体基因。
- 不修改输入文件；原始数据目录中的文件必须保持不变。

## 执行步骤

1. 读取数据，记录原始细胞数和基因数。
2. 计算每个细胞的总 counts、检测基因数和线粒体 counts 比例。
3. 生成 QC 前 violin plot 和 scatter plot。
4. 过滤 `min_genes < 200` 的细胞。
5. 过滤 `min_cells < 3` 的基因。
6. 过滤线粒体比例 `> 20%` 的细胞。
7. 生成 QC 后 violin plot 和 scatter plot。
8. 输出 Markdown 报告，记录每一步过滤后的细胞/基因数量、过滤参数和输出文件路径。
9. 输出 provenance，至少包含输入路径、运行时间、Python 版本、Scanpy 版本和参数。

## 输出契约

- 过滤后的 AnnData 对象（由分析调用方接收；当前 CLI 工作流将统计结果写入输出目录）。
- 报告路径：`output/qc/qc_report.md`。
- 图表：`qc_before.png`、`qc_before_scatter.png`、`qc_after.png`、`qc_after_scatter.png`。
- 机器可读汇总：`output/qc/qc_summary.json`。
- provenance：`output/qc/provenance.json`。

## 验证要求

- 使用 `uv run pytest -q` 运行 QC 测试。
- 报告中的每一步数量必须与 `qc_summary.json` 一致。
- 小于 500 个基因的数据集必须避免调用 Scanpy 默认的 top-500 QC 指标。
