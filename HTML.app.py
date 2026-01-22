import streamlit as st
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readability import Document
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 页面设置 ---
st.set_page_config(
    page_title="全能网页批量转Markdown (Pro+)", 
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 全能网页批量抓取工具 (Pro+)")
st.markdown("""
**支持类型：**
* ✅ **微信公众号**：自动处理防盗链图片、懒加载。
* ✅ **普通博客/新闻/技术文章**：智能识别正文，自动去除广告、导航栏、侧边栏。
* ⚡ **核心引擎**：多线程并发 + 智能重试 + 浏览器仿真。
""")

# --- 核心配置 ---
MAX_WORKERS = 4
MAX_RETRIES = 3

# --- 辅助函数 ---

def get_random_ua():
    ua_list = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/118.0"
    ]
    return random.choice(ua_list)

def fetch_url(url, retries=MAX_RETRIES):
    attempt = 0
    while attempt < retries:
        try:
            time.sleep(random.uniform(0.5, 1.5)) # 随机延迟
            headers = {
                "User-Agent": get_random_ua(),
                "Referer": "https://www.google.com/", # 伪装从谷歌跳转来的
            }
            response = requests.get(url, headers=headers, timeout=15)
            
            # 自动识别编码，防止中文乱码
            response.encoding = response.apparent_encoding
            
            if response.status_code == 403:
                return "ERROR: 403 Forbidden (网站开启了强力反爬)"
            if response.status_code == 404:
                return "ERROR: 404 Not Found (网页不存在)"
            
            response.raise_for_status()
            return response.text
        except Exception as e:
            attempt += 1
            if attempt == retries:
                return f"ERROR: {str(e)}"
            time.sleep(1)

def clean_html_content(soup, base_url):
    """通用HTML清洗：修复相对链接，删除无用标签"""
    # 1. 删除脚本和样式
    for tag in soup(['script', 'style', 'iframe', 'noscript', 'header', 'footer', 'nav']):
        tag.decompose()
    
    # 2. 修复相对链接 (img src="/abc.jpg" -> src="http://site.com/abc.jpg")
    for img in soup.find_all('img'):
        if img.get('src') and not img['src'].startswith('http'):
            # 简单的拼接逻辑，如果要严谨可以用 urljoin
            if img['src'].startswith('//'):
                img['src'] = 'https:' + img['src']
            elif img['src'].startswith('/'):
                domain = '/'.join(base_url.split('/')[:3])
                img['src'] = domain + img['src']
    
    return soup

def process_single_article(url):
    """全能处理逻辑"""
    try:
        html_content = fetch_url(url)
        if html_content.startswith("ERROR:"):
            return None, url, html_content

        # --- 分支 1: 微信公众号专用逻辑 ---
        if "mp.weixin.qq.com" in url:
            soup = BeautifulSoup(html_content, 'html.parser')
            title = soup.find('meta', property='og:title')['content'] if soup.find('meta', property='og:title') else "未命名公众号文章"
            content_div = soup.find('div', id='js_content')
            
            if content_div:
                # 修复公众号懒加载图片
                for img in content_div.find_all('img'):
                    if 'data-src' in img.attrs:
                        img['src'] = img['data-src']
                # 转换为字符串供 markdownify 使用
                final_html = str(content_div)
            else:
                return None, url, "公众号文章解析失败：未找到正文"

        # --- 分支 2: 通用网页逻辑 (Readability 模式) ---
        else:
            # 使用 Readability 提取核心正文
            doc = Document(html_content)
            title = doc.title()
            summary_html = doc.summary() # 这是提取出的“纯净版”HTML
            
            # 二次清洗 (修复图片链接等)
            soup = BeautifulSoup(summary_html, 'html.parser')
            soup = clean_html_content(soup, url)
            final_html = str(soup)

        # --- 统一转 Markdown ---
        # strip=['a'] 表示保留链接但移除a标签? 不，这里我们要保留链接。
        # 可以配置 markdownify 忽略某些标签
        markdown_text = md(final_html, heading_style="ATX")
        
        # 清理标题非法字符
        title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        
        final_block = f"# {title}\n\n> 来源: {url}\n\n{markdown_text}\n\n---\n\n"
        return title, url, final_block

    except Exception as e:
        return None, url, f"处理异常: {str(e)}"

# --- 界面 ---
with st.form("main_form"):
    urls_input = st.text_area(
        "📝 在此粘贴链接 (混合粘贴公众号和普通网页):", 
        height=300
    )
    submitted = st.form_submit_button("🚀 开始全网抓取")

if submitted and urls_input:
    url_list = [line.strip() for line in urls_input.split('\n') if line.strip().startswith('http')]
    
    if not url_list:
        st.error("请粘贴有效的 http 链接")
    else:
        results = []
        errors = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(process_single_article, url): url for url in url_list}
            completed = 0
            
            for future in as_completed(future_to_url):
                title, original_url, content = future.result()
                completed += 1
                progress_bar.progress(completed / len(url_list))
                status_text.text(f"处理中: {completed}/{len(url_list)}")
                
                if title:
                    results.append(content)
                else:
                    errors.append(f"- [失败] {original_url} : {content}")

        # 结果展示
        st.success(f"🎉 成功: {len(results)} | 失败: {len(errors)}")
        
        full_document = f"# 网页抓取合集\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
        if errors:
            full_document += "## ⚠️ 失败列表\n" + "\n".join(errors) + "\n\n---\n\n"
        
        full_document += "".join(results)
        
        st.download_button(
            "📥 下载整合 Markdown",
            data=full_document,
            file_name=f"web_clip_{int(time.time())}.md",
            mime="text/markdown",
            type="primary"
        )