import streamlit as st
import requests
from bs4 import BeautifulSoup
import trafilatura
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipfile
import io

# --- 1. 页面配置与审美优化 ---
st.set_page_config(
    page_title="Magic Clipper | 智能网页剪藏",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 注入自定义 CSS 提升审美 (隐藏默认菜单，优化字体)
st.markdown("""
    <style>
        .reportview-container {
            margin-top: -2em;
        }
        .stDeployButton {display:none;}
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        .stTextArea textarea {
            font-family: "SF Mono", "Roboto Mono", monospace;
            font-size: 14px;
            color: #333;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. 核心工具函数 ---

def get_random_ua():
    """生成随机 User-Agent 防止被简单的反爬拦截"""
    ua_list = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    return random.choice(ua_list)

def fetch_url(url, retries=3):
    """通用的网页下载器，带重试机制"""
    attempt = 0
    while attempt < retries:
        try:
            headers = {"User-Agent": get_random_ua()}
            # 随机延时，对服务器友好一点
            time.sleep(random.uniform(0.3, 1.0))
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # 处理编码问题
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            
            return response.text
        except Exception as e:
            attempt += 1
            if attempt == retries:
                return None
    return None

def clean_filename(title):
    """文件名清洗，防止保存文件时出错"""
    if not title:
        return "Untitled_Document"
    # 去除非法字符
    clean = re.sub(r'[\\/*?:"<>|]', "", title)
    # 压缩多余空格
    clean = " ".join(clean.split())
    return clean[:60]  # 限制长度

# --- 3. 智能解析引擎 (核心逻辑) ---

def parse_wechat(html, url):
    """【专用通道】微信公众号解析逻辑"""
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. 提取标题
    title = soup.find('meta', property='og:title')
    title = title['content'] if title else soup.title.string.strip()
    
    # 2. 提取正文容器
    content_div = soup.find('div', id='js_content')
    if not content_div:
        return title, "Error: 无法找到公众号正文内容，可能是文章已删除或需要登录。"
    
    # 3. 修复图片懒加载 (关键步骤: data-src -> src)
    for img in content_div.find_all('img'):
        if 'data-src' in img.attrs:
            img['src'] = img['data-src']
            # 清理干扰属性
            del img['data-src']
    
    # 4. 转 Markdown (使用 trafilatura 的转换引擎，保持统一)
    # 先转回 string 喂给 trafilatura
    html_str = str(content_div)
    markdown = trafilatura.extract(html_str, include_images=True, include_formatting=True, output_format='markdown')
    
    return title, markdown

def parse_general(html, url):
    """【通用通道】GitBook / Substack / Medium / 博客"""
    # 使用 trafilatura 智能提取，它会自动识别网页的主体内容
    # include_links=False 保持纯净，include_images=True 保留图片链接
    markdown = trafilatura.extract(html, include_images=True, include_formatting=True, output_format='markdown')
    
    # 尝试提取标题
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string.strip() if soup.title else "Unknown_Title"
    
    if not markdown:
        return title, None # 提取失败
        
    return title, markdown

def process_single_url(url):
    """调度器：根据 URL 决定走哪条通道"""
    url = url.strip()
    if not url.startswith('http'):
        return None, url, "Invalid URL"
        
    html = fetch_url(url)
    if not html:
        return None, url, "Network Error: 无法访问链接 (404/403/Timeout)"

    try:
        # === 智能路由 ===
        if "mp.weixin.qq.com" in url:
            title, content = parse_wechat(html, url)
        else:
            title, content = parse_general(html, url)
            
        if not content:
            return title, url, "Content Empty: 解析后内容为空 (可能是反爬或动态渲染)"
            
        # 组装最终结果
        full_doc = f"# {title}\n\n> 来源: {url}\n> 采集时间: {time.strftime('%Y-%m-%d %H:%M')}\n\n---\n\n{content}\n\n"
        return clean_filename(title), url, full_doc
        
    except Exception as e:
        return None, url, f"System Error: {str(e)}"

# --- 4. UI 界面逻辑 ---

st.title("🔮 Magic Clipper")
st.caption("支持：微信公众号 / GitBook / Substack / Medium / 知乎专栏 等")

with st.expander("⚙️ 使用说明 & 设置", expanded=False):
    st.info("💡 **Tips:** \n1. 直接粘贴链接，系统会自动识别来源。\n2. GitBook 如果抓取失败，通常是因为它是纯动态页面，您可以尝试粘贴它的 Sitemap。")
    output_mode = st.radio("下载格式:", ["📦 分文件打包 (ZIP)", "📑 合并为一个 Markdown"], horizontal=True)

# 输入区域
urls_input = st.text_area("🔗在此粘贴链接 (一行一个)", height=150, placeholder="https://mp.weixin.qq.com/s/...\nhttps://docs.gitbook.com/...")

# 执行按钮
if st.button("🚀 开始采集", type="primary"):
    if not urls_input.strip():
        st.warning("⚠️ 请先输入链接")
    else:
        # 清洗输入
        target_urls = [line.strip() for line in urls_input.split('\n') if line.strip().startswith('http')]
        
        if not target_urls:
            st.error("❌ 没有检测到有效的 http/https 链接")
        else:
            success_data = [] # 存 tuple (filename, content)
            fail_log = []     # 存 string
            
            # 进度容器
            progress_bar = st.progress(0)
            status_container = st.status("正在处理任务队列...", expanded=True)
            
            # 线程池执行
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_url = {executor.submit(process_single_url, url): url for url in target_urls}
                
                completed_count = 0
                for future in as_completed(future_to_url):
                    title, url, content = future.result()
                    completed_count += 1
                    progress_bar.progress(completed_count / len(target_urls))
                    
                    if content and not content.startswith(("Network Error", "Content Empty", "System Error", "Error:")):
                        success_data.append((title, content))
                        status_container.write(f"✅ [成功] {title}")
                    else:
                        error_msg = content if content else "Unknown Error"
                        fail_log.append(f"{url} -> {error_msg}")
                        status_container.write(f"❌ [失败] {url} ({error_msg})")
            
            status_container.update(label="✅ 任务完成!", state="complete", expanded=False)
            
            # --- 结果交付区域 ---
            st.divider()
            col1, col2 = st.columns(2)
            col1.metric("成功抓取", len(success_data))
            col2.metric("失败链接", len(fail_log), delta_color="inverse")
            
            if fail_log:
                with st.expander("⚠️ 查看失败日志"):
                    st.text("\n".join(fail_log))
            
            # --- 下载逻辑 ---
            if success_data:
                timestamp = int(time.time())
                
                # 模式 A: ZIP 打包
                if "ZIP" in output_mode:
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
                        for idx, (fname, text) in enumerate(success_data):
                            # 防止重名
                            safe_name = f"{str(idx+1).zfill(2)}_{fname}.md"
                            zf.writestr(safe_name, text.encode('utf-8'))
                        
                        if fail_log:
                            zf.writestr("_FAIL_LOG.txt", "\n".join(fail_log).encode('utf-8'))
                            
                    st.download_button(
                        label="📥 下载 ZIP 压缩包",
                        data=zip_buffer.getvalue(),
                        file_name=f"magic_clipper_{timestamp}.zip",
                        mime="application/zip",
                        type="primary"
                    )
                
                # 模式 B: 合并 Markdown
                else:
                    merged_content = f"# Magic Clipper Export\nDate: {time.strftime('%Y-%m-%d')}\n\n---\n\n"
                    for fname, text in success_data:
                        merged_content += f"{text}\n\n"
                    
                    if fail_log:
                        merged_content += "\n\n# ⚠️ 失败日志\n" + "\n".join(fail_log)
                        
                    st.download_button(
                        label="📥 下载合并文档 (.md)",
                        data=merged_content.encode('utf-8'),
                        file_name=f"merged_export_{timestamp}.md",
                        mime="text/markdown",
                        type="primary"
                    )
