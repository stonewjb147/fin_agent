#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多PDF文件向量库构建脚本
功能：
1. 自动扫描指定文件夹下的所有PDF文件
2. 为每个文档块添加元数据（文件名、来源）
3. 统一构建FAISS向量库
4. 支持按文件名过滤检索

使用方法：
    python build_multi_pdf_index.py --data_dir ./pdfs --index_dir ./faiss_index
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

# 导入必要的库
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
from langchain_core.documents import Document

# 设置环境变量，消除警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def get_all_pdf_files(data_dir: str) -> List[str]:
    """
    获取指定目录下所有PDF文件路径
    
    参数：
        data_dir: PDF文件所在目录
    
    返回：
        PDF文件路径列表
    """
    pdf_files = []
    data_path = Path(data_dir)
    
    if not data_path.exists():
        raise FileNotFoundError(f"目录不存在: {data_dir}")
    
    # 递归查找所有PDF文件
    for file_path in data_path.glob("**/*.pdf"):
        pdf_files.append(str(file_path))
    
    return pdf_files


def load_and_split_pdf(
    pdf_path: str, 
    chunk_size: int = 512, 
    chunk_overlap: int = 100
) -> List[Document]:
    """
    加载并切分单个PDF文件
    
    参数：
        pdf_path: PDF文件路径
        chunk_size: 切分块大小（字符数）
        chunk_overlap: 块之间的重叠字符数
    
    返回：
        切分后的文档块列表（已添加元数据）
    """
    # 获取文件名（不含路径）
    file_name = os.path.basename(pdf_path)
    
    print(f"  正在加载: {file_name}")
    
    try:
        # 加载PDF
        loader = PyPDFLoader(pdf_path)
        pages = loader.load()
        
        # 切分文档
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        )
        chunks = splitter.split_documents(pages)
        
        # 为每个块添加元数据
        for chunk in chunks:
            chunk.metadata["source_file"] = file_name
            chunk.metadata["source_path"] = pdf_path
            chunk.metadata["chunk_size"] = len(chunk.page_content)
        
        print(f"    ✅ 成功加载，共 {len(pages)} 页，切分为 {len(chunks)} 个块")
        return chunks
        
    except Exception as e:
        print(f"    ❌ 加载失败: {e}")
        return []


def build_vectorstore(
    pdf_dir: str,
    index_dir: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
) -> FAISS:
    """
    构建多PDF文件的向量库
    
    参数：
        pdf_dir: PDF文件所在目录
        index_dir: 向量库保存目录
        chunk_size: 切分块大小
        chunk_overlap: 块重叠大小
        embedding_model: 嵌入模型名称
    
    返回：
        FAISS向量库对象
    """
    print("=" * 60)
    print("🔧 多PDF向量库构建工具")
    print("=" * 60)
    
    # 1. 获取所有PDF文件
    print(f"\n📁 扫描目录: {pdf_dir}")
    #pdf_dir="~/users/stonewjb/fin_agent_projects/data"
    pdf_files = get_all_pdf_files(pdf_dir)
    
    if not pdf_files:
        print(f"❌ 未找到任何PDF文件，请检查目录: {pdf_dir}")
        return None
    
    print(f"✅ 找到 {len(pdf_files)} 个PDF文件:")
    for f in pdf_files:
        print(f"   - {os.path.basename(f)}")
    
    # 2. 加载并切分所有PDF
    print(f"\n📄 开始加载PDF文件...")
    all_chunks = []
    
    for pdf_path in pdf_files:
        chunks = load_and_split_pdf(pdf_path, chunk_size, chunk_overlap)
        all_chunks.extend(chunks)
    
    if not all_chunks:
        print("❌ 没有成功加载任何文档块")
        return None
    
    print(f"\n✅ 总共加载 {len(all_chunks)} 个文档块")
    
    # 3. 加载嵌入模型
    print(f"\n🔧 加载嵌入模型: {embedding_model}")
    embeddings = HuggingFaceEmbeddings(
        model_name=embedding_model,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    print("✅ 嵌入模型加载完成")
    
    # 4. 构建向量库
    print(f"\n🏗️ 构建FAISS向量库...")
    vectorstore = FAISS.from_documents(all_chunks, embeddings)
    
    # 5. 保存向量库
    print(f"\n💾 保存向量库到: {index_dir}")
    vectorstore.save_local(index_dir)
    
    # 6. 统计信息
    total_chars = sum(len(chunk.page_content) for chunk in all_chunks)
    print("\n" + "=" * 60)
    print("📊 构建统计")
    print("=" * 60)
    print(f"   PDF文件数: {len(pdf_files)}")
    print(f"   文档块总数: {len(all_chunks)}")
    print(f"   总字符数: {total_chars:,}")
    print(f"   平均块大小: {total_chars // len(all_chunks):,} 字符")
    print(f"   向量库路径: {index_dir}")
    print("=" * 60)
    
    return vectorstore


def search_demo(vectorstore: FAISS, query: str, filter_source: str = None):
    """
    演示检索功能
    
    参数：
        vectorstore: FAISS向量库
        query: 查询问题
        filter_source: 可选，按源文件过滤
    """
    print(f"\n🔍 检索测试: {query}")
    
    if filter_source:
        print(f"   过滤条件: source_file = {filter_source}")
        results = vectorstore.similarity_search(
            query, 
            k=3,
            filter={"source_file": filter_source}
        )
    else:
        results = vectorstore.similarity_search(query, k=3)
    
    print(f"\n   找到 {len(results)} 个相关文档块:")
    for i, doc in enumerate(results, 1):
        print(f"\n   [{i}] 来源: {doc.metadata.get('source_file', '未知')}")
        print(f"       内容预览: {doc.page_content[:150]}...")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="多PDF向量库构建工具")
    parser.add_argument(
        "--data_dir", 
        type=str, 
        default="/users/stonewjb/fin_agent_projects/data",
        help="PDF文件所在目录（默认: ./pdfs）"
    )
    parser.add_argument(
        "--index_dir", 
        type=str, 
        default="/users/stonewjb/fin_agent_projects/faiss_index",
        help="向量库保存目录（默认: ./faiss_index）"
    )
    parser.add_argument(
        "--chunk_size", 
        type=int, 
        default=1000,
        help="切分块大小（字符数，默认: 1000）"
    )
    parser.add_argument(
        "--chunk_overlap", 
        type=int, 
        default=200,
        help="块重叠大小（字符数，默认: 200）"
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default="BAAI/bge-small-zh-v1.5",
        help="嵌入模型名称（默认: BAAI/bge-small-zh-v1.5）"
    )
    parser.add_argument(
        "--test_query", 
        type=str, 
        default=None,
        help="测试查询问题"
    )
    
    args = parser.parse_args()
    
    # 构建向量库
    vectorstore = build_vectorstore(
        pdf_dir=args.data_dir,
        index_dir=args.index_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embedding_model=args.model
    )
    
    if vectorstore is None:
        sys.exit(1)
    
    # 如果提供了测试查询，执行检索演示
    if args.test_query:
        search_demo(vectorstore, args.test_query)
    
    # 可选：列出所有可用的源文件
    print("\n📋 已索引的PDF文件列表:")
    # 注意：FAISS 不直接存储源文件列表，这里从统计信息中获取
    print("   请查看上面的加载日志获取文件列表")


if __name__ == "__main__":
    main()