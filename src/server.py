from aiohttp import web
import asyncio
from log_analyzer import MosDNSLogAnalyzer
import json
import os
import logging
from aiohttp.web_runner import GracefulExit

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

routes = web.RouteTableDef()
analyzer = MosDNSLogAnalyzer()

# 添加WebSocket连接存储
ws_connections = set()

@routes.get('/favicon.svg')
async def favicon(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), 'static/favicon.svg'))

@routes.get('/')
async def index(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), 'static/index.html'))

@routes.get('/ws')
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_connections.add(ws)
    
    try:
        async for msg in ws:
            pass  # 我们只需要保持连接开启
    finally:
        ws_connections.remove(ws)
    return ws

@routes.get('/stats')
async def get_stats(request):
    limit = int(request.query.get('limit', 10))  # 默认显示10条
    stats = await analyzer.get_statistics(limit)
    # 只返回黑名单过滤的域名数量
    stats['blacklist_stats'] = {
        'unique_blocked_domains': len(analyzer.blacklisted_domains)
    }
    return web.json_response(stats)

async def notify_clients():
    """通知所有WebSocket客户端更新数据"""
    if ws_connections:
        for ws in ws_connections.copy():
            try:
                await ws.send_str('update')
            except Exception:
                ws_connections.discard(ws)

async def start_monitoring(app):
    """启动监控作为后台任务"""
    log_file = "mosdns.log"
    if not os.path.exists(log_file):
        open(log_file, 'a').close()
        logger.info("创建新日志文件")
    
    logger.info(f"开始监控日志文件: {log_file}")
    app['monitor_task'] = asyncio.create_task(
        analyzer.monitor_log(log_file, notify_clients)
    )

async def cleanup_background_tasks(app):
    """清理后台任务"""
    logger.info("停止监控")
    app['monitor_task'].cancel()
    try:
        await app['monitor_task']
    except asyncio.CancelledError:
        pass

def init_app():
    app = web.Application()
    
    # 修正路由注册
    app.add_routes([
        web.get('/', index),
        web.get('/ws', websocket_handler),
        web.get('/stats', get_stats),
        web.get('/favicon.svg', favicon),  # 添加favicon.svg路由
    ])
    
    # CORS 中间件
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == 'OPTIONS':
            response = web.Response()
        else:
            response = await handler(request)
            
        response.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '86400',
        })
        return response

    app.middlewares.append(cors_middleware)
    
    # 错误处理中间件
    @web.middleware
    async def error_middleware(request, handler):
        try:
            return await handler(request)
        except Exception as error:
            logger.error(f"Error handling request: {error}")
            return web.json_response({
                'error': str(error),
                'status': 'error'
            }, status=500)
    
    app.middlewares.append(error_middleware)
    
    # 添加启动和清理回调
    app.on_startup.append(start_monitoring)
    app.on_cleanup.append(cleanup_background_tasks)
    
    return app

if __name__ == "__main__":
    logger.info("启动服务器...")
    app = init_app()
    web.run_app(app, host='127.0.0.1', port=8000, access_log=None)