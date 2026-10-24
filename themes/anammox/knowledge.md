# 厌氧氨氧化领域知识库（RAG 检索源）

每个 `## ` 标题为一条独立知识条目，按与题录的相似度检索注入评审 prompt。
聚焦术语消歧与判定边界，中英文术语并写。

## anammox 反应的定义与化学计量
厌氧氨氧化（anaerobic ammonium oxidation, anammox）：NH4+ 与 NO2- 在缺氧条件下
被 anammox 菌直接氧化为 N2 的生物过程，总反应约 NH4+ + NO2- → N2 + 2H2O，
伴随少量 NO3- 生成（约 11% 进水氮）。anammox 菌属浮霉菌门（Planctomycetes），
常用属名：Candidatus Brocadia、Kuenenia、Anammoxoglobus、Jettenia、Scalindua。
关键词：anaerobic ammonium oxidation, anammox, deammonification。

## anammox 工艺家族术语对照
含 anammox 环节的耦合工艺家族：一段式/一体化 partial nitritation-anammox
（PN/A、CANON=completely autotrophic nitrogen removal over nitrite、
OLAND=oxygen-limited autotrophic nitrification denitrification、DEMON、SNAP）；
两段式 Sharon-Anammox；SNAD（simultaneous partial Nitrification, Anammox and
Denitrification）；短程反硝化耦合（partial denitrification-anammox, PdN-A、
deamox、PD-A）；氨氧化真菌/古菌辅助供底等。文献出现这些缩写通常即含 anammox
环节。注意 "nitritation"=短程硝化（只到 NO2-），"nitrification"=全程硝化（到 NO3-）。

## anammox 与传统硝化-反硝化的区分（易混淆一）
传统生物脱氮：好氧硝化（NH4+→NO2-→NO3-）+ 缺氧反硝化（NO3-→NO2-→N2），
依赖有机碳源（BOD/COD）。anammox 路线：无需有机碳、曝气量低、污泥产量低。
判别要点：研究若仅涉及 nitrification/denitrification、HN-AD（好氧反硝化）、
厌氧氨氧化未出现，则不属于 anammox 研究。"single reactor high-rate ammonium
removal"类命名需查是否为 PN/A。短程硝化（nitritation/partial nitrification）
单独研究（如抑制 NOB）若系统目标是为 anammox 供底 → 属 anammox 工艺链。

## 主流与侧流（mainstream vs sidestream）的区分
侧流/旁路（sidestream）：污泥消化液/脱水滤液（reject water, centrate,
digested dewatering liquid, sludge liquor），氨氮高（500-2000 mg N/L）、温度高，
是 anammox 首个工程化场景（如 Strass 厂 DEMON 工艺）。主流（mainstream）：
城市污水厂进水/曝气池主流线，低氨氮（30-80 mg N/L）、低温，anammox 应用难度大，
是研究热点。二者均属"废水处理场景"。_KEYWORDS: mainstream deammonication,
sidestream, reject water, centrate._

## anammox 研究的常见基质与废水类型
真实基质：城市污水（raw/settled wastewater）、污泥消化液、垃圾渗滤液
（landfill leachate，高氨氮、抑制物多）、养殖废水、焦化废水、制药/抗生素废水、
味精/淀粉废水、半导体含氨废水、source-separated urine（黄水）。合成基质
（synthetic medium / synthetic wastewater）：无机盐培养基+NH4Cl+NaNO2，
常加微量元素。机理研究多用合成基质——合成基质研究仍属废水处理研究范畴
（本判据包 A3 口径）。

## anammox 关键性能指标释义
NLR（nitrogen loading rate，氮容积负荷，kg N/m3/d）、NRR（nitrogen removal
rate，氮去除速率）、NRE（nitrogen removal efficiency，氮去除率%）、SAA
（specific anammox activity，比活性）、anammox contribution（anammox 对总脱氮
的贡献率）。物料衡算指标：ΔNO2-/ΔNH4+ 比（理论 1.32）、ΔNO3-/ΔNH4+ 比
（理论 0.11-0.26，偏高指示 NOB 活性或高 DO）。出现这些指标通常表明研究以
脱氮性能为核心。

## anammox 菌的抑制因素与工况边界
游离氨（FA, free ammonia）与游离亚硝酸（FNA, free nitrous acid）在高浓度抑制
anammox 菌（侧流场景常见瓶颈）；低温（<15°C）显著降低活性（主流挑战）；
高盐、高 COD（异养菌竞争）、硫化物、抗生素/药物抑制也是常见研究对象。
DO 控制是一段式工艺核心（抑制 NOB 又不抑制 AOA/AOB）。这些主题的研究
（"inhibition of anammox by ..."）属于 A1/A2 范畴。

## anammox 反应器构型与菌体持留方式
主流构型：颗粒污泥（granular sludge）SBR/气提反应器、生物膜载体 MBBR/IFAS、
RBC（旋转生物接触）、填充床、海绵/无纺布载体、微孔膜供氧（MABR）。
一段式 vs 两段式（separate reactors for PN and anammox）。生物滞留（bio-retention、
hydraulic retention time HRT、SRT）与 "retention" 词常出现。构型研究属工艺研究。

## anammox 与厌氧消化/污泥处理的关联（易混淆二）
厌氧消化（anaerobic digestion, AD）产甲烷与 anammox 是不同过程；但
"侧流 anammox 处理消化液"是典型场景，"AD + anammox 联合工艺"（如厌氧出水
后接 PN/A）属 A1+A3。仅研究厌氧消化/产甲烷/污泥厌氧稳定化、无 anammox
环节的文献不纳入。厌氧氨氧化曾被误写为"厌氧硝化"，注意与 anammox 区分。

## 海洋/土壤/天然水体 anammox 研究的排除（易混淆三）
Scalindua 属是海洋环境 anammox 的主要菌属；海洋/河口/沉积物/农田土壤氮循环中
的 anammox 生态研究（nitrifier-denitrification、dnfra 同步硝化反硝化等）不属
废水处理场景（A3 答 No）。判别要点：研究基质是否为天然水体/沉积物/土壤，
是否有废水处理（wastewater treatment）语境。

## 研究类型判别要点（A4 辅助）
综述标志词：review、state of the art、advances in、progress in、perspective、
critical review、systematic review、meta-analysis、mini-review。研究性论文标志：
含具体实验条件（反应器容积、HRT、进水浓度）、定量结果（去除率、速率、
丰度）、材料与方法/结果讨论结构。会议摘要通常仅一页且无数据。建模研究
（ASM 模型扩展、CFD、机器学习）在本主题口径下算研究性论文，判别时看是否
有原创模型构建或验证，而非仅调用现成软件。

## 发表语种判别要点（A5 辅助）
英语文献的标题、摘要、关键词均为英语。非英语文献特征：题录含德/法/中/日/
韩/俄/西语关键词（如 "Untersuchungen"、"étude"、"研究"、"評価"）；英语题录
但期刊为明显本国语言期刊（刊名含中文/西里尔字母等）。OpenAlex/WoS 的语种
元数据缺失时按标题摘要语种判定。
