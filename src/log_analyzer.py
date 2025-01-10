import re
import json
from collections import defaultdict, Counter
import aiohttp
import os
import asyncio
from datetime import datetime, timedelta
import time  # 添加time模块
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class LogFileHandler(FileSystemEventHandler):
    def __init__(self, analyzer, callback):
        self.analyzer = analyzer
        self.callback = callback
        self.last_modified = 0
        self._debounce_timer = None
    
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            current_time = time.time()
            # 防抖:确保在文件变化后0.5秒内只处理一次
            if current_time - self.last_modified > 0.5:
                self.last_modified = current_time
                if self._debounce_timer:
                    self._debounce_timer.cancel()
                self._debounce_timer = asyncio.create_task(self._delayed_process())

    async def _delayed_process(self):
        await asyncio.sleep(0.5)  # 等待文件写入完成
        self.analyzer.analyze_log(self.analyzer.current_log)
        if self.callback:
            await self.callback()

class MosDNSLogAnalyzer:
    def __init__(self):
        self.total_requests = 0
        self.cache_hits = 0
        self.domain_stats = defaultdict(lambda: {
            "requests": 0, 
            "cache_hits": 0,
            "details": {
                "ips": defaultdict(int),
                "types": defaultdict(int)
            }
        })
        self.client_stats = Counter()
        self.ip_location_cache = {}
        self.ip_cache_file = "ip_cache.json"
        self._load_ip_cache()
        self.semaphore = asyncio.Semaphore(2)  # 限制最大并发数为2
        self.query_types = Counter()  # 添加请求类型统计
        self.start_time = None  # 添加统计开始时间
        self.end_time = None    # 添加统计结束时间
        self.processing_start = None  # 添加处理开始时间
        self.processing_end = None    # 添加处理结束时间
        self.processing_start_ms = None  # 使用毫秒级时间戳
        self.processing_end_ms = None
        # 预编译正则表达式
        self.domain_pattern = re.compile(r'"query":\s*"([^"]+)\.\s+IN\s+([A-Z]+)\s+\d+\s+\d+\s+(\d+\.\d+\.\d+\.\d+)"')
        self.cache_hit_pattern = re.compile(r'cache hit')
        self.entry_returned_pattern = re.compile(r'entry returned')
        self.batch_size = 8192  # 8KB 缓冲区大小
        self.blacklist_file = "blacklist.json"
        self.blacklist = self._load_blacklist()
        self.current_log = None
        self.observer = None
        self.file_handler = None
        self.last_size = 0
        self.last_check = 0
        self.check_interval = 1  # 检查间隔(秒)
        self.last_blacklist_check = 0
        self.blacklist_mtime = 0
        self._update_blacklist()  # 初始化时加载黑名单
        self.blacklisted_requests = 0  # 添加黑名单请求计数器
        self.blacklisted_domains = set()  # 添加被拦截的域名集合
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("aiohttp").setLevel(logging.WARNING)

    def _load_ip_cache(self):
        try:
            if os.path.exists(self.ip_cache_file):
                with open(self.ip_cache_file, 'r', encoding='utf-8') as f:
                    self.ip_location_cache = json.load(f)
        except Exception as e:
            logger.error(f"加载IP缓存失败: {e}")

    def _save_ip_cache(self):
        try:
            with open(self.ip_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.ip_location_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving IP cache: {e}")

    def _load_blacklist(self):
        try:
            if os.path.exists(self.blacklist_file):
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading blacklist: {e}")
        return {"domains": [], "patterns": []}

    def _is_blacklisted(self, domain):
        """检查域名是否在黑名单中"""
        # 检查完整域名匹配
        if domain in self.blacklist.get('domains', []):
            return True
            
        # 检查关键词匹配 - 改进匹配逻辑
        return any(pattern in domain.lower() for pattern in self.blacklist.get('patterns', []))

    def _update_blacklist(self):
        """检查并更新黑名单"""
        try:
            if not os.path.exists(self.blacklist_file):
                logger.warning("黑名单文件不存在")
                self.blacklist = {"domains": [], "patterns": []}
                return False
                
            current_mtime = os.path.getmtime(self.blacklist_file)
            if current_mtime != self.blacklist_mtime:
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    self.blacklist = json.load(f)
                self.blacklist_mtime = current_mtime
                # 删除旧的编译正则表达式属性
                if hasattr(self, 'blacklist_patterns'):
                    delattr(self, 'blacklist_patterns')
                logger.info("黑名单已更新")
                return True
            
            return False
        except Exception as e:
            logger.error(f"更新黑名单失败: {e}")
            return False

    async def _get_ip_location(self, ip):
        if ip in self.ip_location_cache:
            return self.ip_location_cache[ip]
        
        async with self.semaphore:  # 使用信号量控制并发
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f'https://api.ip.sb/geoip/{ip}') as response:
                        if response.status == 200:
                            data = await response.json()
                            location = [
                                data.get('country', '未知'),
                                data.get('region', ''),
                                data.get('isp', '')
                            ]
                            location = ' | '.join(filter(None, location))
                            self.ip_location_cache[ip] = location
                            self._save_ip_cache()
                            await asyncio.sleep(1)  # 增加请求间隔到1秒
                            return location
                        elif response.status == 429:  # 如果遇到限流
                            logger.info(f"Rate limited for IP {ip}, waiting 5 seconds...")
                            await asyncio.sleep(5)  # 遇到限流等待更长时间
                            return await self._get_ip_location(ip)  # 重试
            except Exception as e:
                logger.error(f"Error querying IP location for {ip}: {e}")
            return "未知"
        
    def analyze_log(self, log_file):
        self.processing_start = datetime.now()  # 记录开始时间
        self.processing_start_ms = time.time() * 1000  # 记录开始时间(毫秒)
        # 重置所有计数器
        self.total_requests = 0
        self.cache_hits = 0
        self.domain_stats.clear()
        self.client_stats.clear()
        self.query_types.clear()  # 重置请求类型统计
        self.start_time = None
        self.end_time = None
        self.blacklisted_requests = 0  # 重置黑名单请求计数器
        self.blacklisted_domains.clear()  # 重置被拦截的域名集合
        
        with open(log_file, 'r', encoding='utf-8') as f:
            buffer = ""
            while True:
                chunk = f.read(self.batch_size)
                if not chunk:
                    break
                
                buffer += chunk
                lines = buffer.split('\n')
                
                # 保留最后一行，因为可能不完整
                buffer = lines[-1]
                lines = lines[:-1]
                
                # 批量处理日志行
                self._process_log_lines(lines)
            
            # 处理最后的缓冲区
            if buffer:
                self._process_log_lines([buffer])
        self.processing_end = datetime.now()    # 记录结束时间
        self.processing_end_ms = time.time() * 1000  # 记录结束时间(毫秒)

    def _process_log_lines(self, lines):
        """批量处理日志行"""
        current_domain = None
        current_client = None
        current_type = None  # 添加当前查询类型
        is_cache_hit = False
        
        for line in lines:
            # 解析时间戳
            timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{4})', line)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                if not self.start_time:
                    self.start_time = timestamp
                self.end_time = timestamp

            # 使用预编译的正则表达式
            if self.cache_hit_pattern.search(line):
                is_cache_hit = True
                
            if '"query":' in line:
                domain_match = self.domain_pattern.search(line)
                if domain_match:
                    current_domain = domain_match.group(1)
                    current_type = domain_match.group(2)  # 捕获查询类型
                    current_client = domain_match.group(3)
                    # 更新黑名单检查逻辑
                    if self._is_blacklisted(current_domain):
                        self.blacklisted_requests += 1
                        self.blacklisted_domains.add(current_domain)
                        current_domain = None  # 清除当前域名，不计入统计
                        current_type = None    # 清除当前类型
                        current_client = None  # 清除当前客户端
                        is_cache_hit = False   # 重置缓存命中标志
            
            # 只有非黑名单域名才会被统计
            if self.entry_returned_pattern.search(line) and current_domain and current_client:
                self.total_requests += 1
                self.domain_stats[current_domain]["requests"] += 1
                self.domain_stats[current_domain]["details"]["ips"][current_client] += 1
                self.domain_stats[current_domain]["details"]["types"][current_type] += 1
                self.client_stats[current_client] += 1
                self.query_types[current_type] += 1  # 统计查询类型
                
                if is_cache_hit:
                    self.cache_hits += 1
                    self.domain_stats[current_domain]["cache_hits"] += 1
                
                current_domain = None
                current_client = None
                current_type = None
                is_cache_hit = False

    async def get_statistics(self, limit=10):
        # 转换时间格式为人类可读格式
        def format_time(timestamp):
            if not timestamp:
                return "-"
            try:
                dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                return timestamp

        # 计算耗时(毫秒)
        processing_duration = int(self.processing_end_ms - self.processing_start_ms)
        duration_str = f"{processing_duration}毫秒"
        # 获取基础统计信息
        stats = {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "hit_rate": round((self.cache_hits / self.total_requests * 100), 2) if self.total_requests > 0 else 0,
            "time_range": {
                "start": format_time(self.start_time),
                "end": format_time(self.end_time)
            },
            "analysis_info": {
                "start_time": datetime.fromtimestamp(self.processing_start_ms/1000).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": datetime.fromtimestamp(self.processing_end_ms/1000).strftime("%Y-%m-%d %H:%M:%S"),
                "duration": duration_str
            }
        }

        # 获取域名统计
        top_domains = sorted(
            [(domain, stats["requests"], stats["cache_hits"]) 
             for domain, stats in self.domain_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )[:limit]  # 使用传入的limit参数

        stats["top_domains"] = [
            {
                "domain": domain,
                "requests": requests,
                "cache_hits": hits,
                "hit_rate": round((hits/requests * 100), 2) if requests > 0 else 0,
                "details": {
                    "ips": dict(self.domain_stats[domain]["details"]["ips"]),
                    "types": dict(self.domain_stats[domain]["details"]["types"])
                }
            }
            for domain, requests, hits in top_domains
        ]

        # 获取客户端统计，先返回基本信息
        top_clients = self.client_stats.most_common(10)
        stats["top_clients"] = [
            {
                "ip": ip,
                "requests": count,
                "location": self.ip_location_cache.get(ip, "未知")  # 优先使用缓存
            }
            for ip, count in top_clients
        ]

        # 异步更新未缓存的IP位置信息，分批处理
        uncached_ips = [ip for ip, _ in top_clients if ip not in self.ip_location_cache]
        if uncached_ips:
            tasks = []
            for ip in uncached_ips:
                tasks.append(self._get_ip_location(ip))
            # 使用gather而不是直接创建所有task
            await asyncio.gather(*tasks)
            self._save_ip_cache()

        # 添加查询类型统计
        stats["query_types"] = [
            {
                "type": qtype,
                "count": count
            }
            for qtype, count in sorted(
                self.query_types.items(),
                key=lambda x: x[1],
                reverse=True
            )
        ]

        # 简化黑名单统计信息
        stats["blacklist_stats"] = {
            "unique_blocked_domains": len(self.blacklisted_domains)
        }

        return stats

    async def monitor_log(self, log_file, callback):
        """异步监控日志文件变化"""
        while True:
            try:
                current_time = time.time()
                
                # 每5秒检查一次黑名单更新
                if current_time - self.last_blacklist_check > 5:
                    self.last_blacklist_check = current_time
                    if self._update_blacklist():
                        # 如果黑名单更新了，重新分析日志
                        self.analyze_log(log_file)
                        if callback:
                            await callback()
                
                if current_time - self.last_check < self.check_interval:
                    await asyncio.sleep(0.1)
                    continue
                
                self.last_check = current_time
                current_size = os.path.getsize(log_file)
                
                if current_size > self.last_size:
                    size_mb = current_size / (1024 * 1024)
                    logger.info(f"检测到日志更新，当前大小: {size_mb:.2f}MB")
                    self.analyze_log(log_file)
                    self.last_size = current_size
                    if callback:
                        try:
                            await callback()
                        except Exception as e:
                            logger.error(f"回调错误: {e}")
                
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"监控错误: {e}")
                await asyncio.sleep(self.check_interval)

if __name__ == "__main__":
    analyzer = MosDNSLogAnalyzer()
    analyzer.analyze_log("mosdns.log")
    result = asyncio.run(analyzer.get_statistics())
    print(json.dumps(result, indent=2))