# omics-scientist QC 评估报告

- 输入：`data/sample.h5ad`
- 评估状态：`not_assessable`
- 细胞数：120
- QC 通过比例：22.5%
- 中位检测基因数：195.0
- 中位线粒体比例：0.30%

## 批次字段

发现字段：无


## 下一步建议

- 未发现批次元数据，当前不能可靠判断批次效应。请在 adata.obs 中提供 batch/sample/donor/library 等字段。
- 补充批次字段后，重新运行本评估器并比较各批次 QC 指标及下游聚类结构。
