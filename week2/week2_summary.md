# 第二周学习总结：Agentic RAG 智能投研问答

## 完成时间
2026年5月26日

## 学习目标
实现对年报/研报的严谨问答，从朴素 RAG 升级到 Agentic RAG。

## 技术栈
- **PDF 加载**：LangChain PyPDFLoader
- **文本分块**：RecursiveCharacterTextSplitter（chunk_size=500, overlap=50）
- **嵌入模型**：BAAI/bge-small-zh-v1.5（约100MB，CPU推理）
- **向量数据库**：FAISS（CPU版本，内存友好）
- **大模型**：DeepSeek Chat API（deepseek-chat）/
- **智能体框架**：LangChain ReAct Agent + AgentExecutor
- **多轮记忆**：ConversationBufferMemory

## 项目文件结构


## 关键成果
1. ✅ 成功加载贵州茅台2025年年报PDF（120+页）
2. ✅ 构建了FAISS向量索引，支持语义检索
3. ✅ 实现了朴素RAG：检索+生成
4. ✅ 升级为Agentic RAG：智能体自主判断是否需要检索
5. ✅ 闲聊问题不触发检索，节省Token
6. ✅ 实现了多轮对话记忆，支持代词指代理解
7. ✅ 14项测试全部通过

## 踩坑记录
1. **ReAct格式问题**：DeepSeek 在闲聊时不输出 `Action:`，导致解析失败。通过修改提示词，明确两种回答格式解决。
2. **langchain-huggingface 版本冲突**：新包与当前 langchain-core 版本不兼容，回退到 `langchain_community.embeddings` 解决。
3. **PDF文本解析差异**：PDF中的"净利润"可能被解析为不同形式，检索关键词需宽松匹配。

## 下一步
进入第三周：全球情报守望者——新闻抓取、主题聚类、结构化信号输出。
pdf---chunks----embedding----vectorstore---rag(retrieval)---+prompts----llm