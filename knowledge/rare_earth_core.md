# 稀土领域知识库

以下每个 `## ` 标题为一条独立知识条目，将作为 RAG 检索单元注入评审 prompt。
条目应保持简短、定义式，聚焦术语消歧、元素分类与技术边界。

## 稀土元素的定义与完整清单
稀土元素（Rare Earth Elements, REEs）共 17 种：钪（Sc, 21）、钇（Y, 39）及镧系元素 15 种（La, 57 至 Lu, 71）。镧系元素（lanthanides）仅指 La-Lu，不含 Sc 和 Y。因此文献中出现"lanthanide"不等于包含 Sc/Y；反之"rare earth"应包含 Sc、Y。常见缩写：REE=稀土元素，REY=稀土元素+钇，REO=稀土氧化物（常用于计量品位），REMs=稀土金属/磁体（Rare Earth Metals 或 Magnets，需结合上下文区分）。

## 轻、中、重稀土的划分差异
轻稀土（LREE）：La, Ce, Pr, Nd（部分口径含 Sm）。中稀土（MREE）：Sm, Eu, Gd（部分口径含 Tb, Dy）。重稀土（HREE）：Tb/Ho 至 Lu 及 Y。注意：IUPAC 无官方划分，中国学界与西方文献口径不同（如是否含 Sc）。文献间划分不一致是常态，不应作为否决判定的依据；仅当研究结论依赖某种特定划分且明显错误时才需质疑。

## 稀土元素常见的赋存形式与价态
稀土在自然界主要以 +3 价存在，常见矿物：氟碳铈矿（bastnäsite，主要轻稀土）、独居石（monazite，轻稀土+Th）、离子吸附型稀土矿（ion-adsorption clay，中国南方，中重稀土为主）、磷灰石/磷钇矿（xenotime，重稀土）。Ce 可为 +4 价（CeO2），Eu 可为 +2 价，这一价态差异常被用于稀土分离（如 Ce4+ 的萃取/还原分离、Eu2+ 的选择性沉淀）。

## 回收（recycling）与提取（extraction）的区分
二次资源回收（recycling）：处理对象为废旧产品或工业废料，如废旧 NdFeB 磁体、废弃荧光粉（phosphor）、镍氢电池负极、废抛光粉、稀土尾矿再利用。原生资源提取（extraction/mining）：处理对象为矿石或卤水。二者都属于稀土的获取途径，但工艺路线与经济性不同；筛选时按判据 T2 决定是否限定二次资源。

## 废旧 NdFeB 磁体回收的典型工艺
废旧钕铁硼（NdFeB）磁体回收路径：(1) 湿法：盐酸/硫酸浸出全溶后溶剂萃取分离 Nd/Dy/Pr；(2) 氢破碎（hydrogen decrepitation, HD）：H2 使磁体沿晶界脆化碎裂，可直接获得可再烧结的磁粉（短流程回收）；(3) 晶界扩散修复（grain boundary diffusion / re-sintering）：将回收磁粉再制造；(4) 熔盐电解。若文献涉及"hydrogen decrepitation"或"heavy rare earth grain boundary diffusion"用于废磁体，属回收工艺。

## 荧光粉与镍氢电池中的稀土
废弃荧光灯/LED 荧光粉含多种稀土相：Y2O3:Eu3+（红色）、LaPO4:Ce,Tb（绿色）、BaMgAl10O17:Eu2+（蓝色）、CeMgAl11O19 等。荧光粉回收研究通常涉及酸浸+选择性沉淀/萃取分离 Y/Eu/Tb/Ce。镍氢电池（NiMH）负极储氢合金为 LaNi5 型（含 La, Ce, Nd 等），回收研究涉及浸出提 La/Nd 或直接再生合金。

## 溶剂萃取分离稀土的基本概念
稀土溶剂萃取分离常用萃取剂：P507（2-乙基己基膦酸单2-乙基己基酯）、P204（D2EHPA）、Cyanex 272、N235（三烷基胺）、环烷酸；串级萃取（cascade extraction）与分馏萃取是工业分离的核心方法。分离系数（separation factor, β）与分配比（D）是关键指标。皂化（saponification）指将萃取剂转为铵/钠盐以提高萃取能力。

## 离子吸附型稀土矿的浸出
离子吸附型稀土矿（风化壳型）中稀土以离子态吸附于黏土矿物，可用电解质溶液（历史上 NaCl，现行硫酸铵 (NH4)2SO4）进行离子交换浸出。相关术语：in-situ leaching（原地浸矿）、ammonium sulfate leaching、ion-exchangeable fraction。镁盐浸出（MgSO4）是为降低铵盐污染的研究方向。此类研究属原生稀土提取。

## 稀土回收中的常见易混淆情形一：掺杂/载体 vs 回收对象
大量材料研究使用稀土作为掺杂剂（如 La 掺杂 TiO2 光催化剂、CeO2 载体、Y 稳定 ZrO2），此类文献中稀土不作为回收目标。判断要点：研究目的是否包含"将稀土从体系中分离/提取出来并回收"。若文献标题/摘要出现 recovery/recycling 且对象是稀土本身（如 "recovery of Nd and Dy from waste magnets"），则属回收；若仅出现稀土掺杂材料的制备与性能，则不是。

## 稀土回收中的常见易混淆情形二：伴生金属
稀土废料常伴生 Fe、Co、Ni、B（NdFeB）或 Ca、P（荧光粉）等。回收工艺研究中伴生金属的去除（如除铁）属于稀土回收流程的一部分，不应因此将文献判定为"非稀土研究"。判断核心：稀土是否为主要回收目标。

## 环境与毒理方向与本判据包的关系
稀土环境研究（如稀土开采区污染、土壤/水体中 REE 分布、生态毒理）若不包含稀土的回收/分离工艺，不属于"稀土回收"主题。但"从废水中吸附回收稀土"（sorption/recovery of REEs from wastewater）属于回收，注意区分"去除以治理污染"（removal）与"回收以再利用"（recovery/recycling）——许多文献两者兼有，此时按判据 T1 判断稀土回收是否为明确目的。

## 纯计算研究与实验研究的区分
DFT 计算、CALPHAD、分子动力学（MD）、CFD 模拟、机器学习建模本身不产生实验数据；但"模拟+实验验证"的研究属于实验研究。判断要点：摘要中是否报告了实验测定的定量结果（回收率、萃取率、浸出效率、纯度等实测值）。仅有模拟预测值而无实验测定 → 本判据 T3 应答 No。
