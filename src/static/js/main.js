async function getIpLocation(ip) {
    try {
        const response = await fetch(`https://api.ip.sb/geoip/${ip}`);
        if (response.ok) {
            const data = await response.json();
            const location = [
                data.country || '未知',
                data.region || '',
                data.isp || ''
            ].filter(Boolean).join(' | ');
            return location;
        }
    } catch (error) {
        console.error(`Error fetching location for IP ${ip}:`, error);
    }
    return '未知';
}

// 复制IP地址到剪贴板
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showCopySuccess();
    }).catch(err => {
        console.error('复制失败:', err);
    });
}

// 更新客户端统计表格
async function updateClientStats(clients) {
    const clientTbody = document.getElementById('clientStats');
    clientTbody.innerHTML = '';

    for (const client of clients) {
        clientTbody.innerHTML += `
            <tr>
                <td class="ip-cell">
                    <code class="blurred-ip" onclick="copyToClipboard('${client.ip}')">${client.ip}</code>
                </td>
                <td>${client.requests}</td>
                <td><small>${client.location}</small></td>
            </tr>
        `;
    }
}

// 显示/隐藏加载动画
function toggleLoading(show) {
    document.getElementById('loadingBar').style.display = show ? 'block' : 'none';
}

// 从后端获取数据并更新页面
async function fetchData() {
    toggleLoading(true);
    try {
        const topN = document.getElementById('topNSelect').value;
        const response = await fetch(`http://localhost:8000/stats?limit=${topN}`);
        const data = await response.json();

        // 更新时间信息
        if (data.time_range) {
            document.getElementById('timeRange').textContent =
                `统计时段: ${data.time_range.start} 至 ${data.time_range.end}`;
        }
        if (data.analysis_info) {
            document.getElementById('analysisInfo').textContent =
                `分析耗时: ${data.analysis_info.duration}`;
        }

        // 更新概览统计
        document.getElementById('totalRequests').textContent = data.total_requests;
        document.getElementById('cacheHits').textContent = data.cache_hits;
        document.getElementById('hitRate').textContent = data.hit_rate + '%';

        // 更新已过滤数量 - 只显示过滤的域名数量
        if (data.blacklist_stats) {
            document.getElementById('filteredInfo').textContent =
                `已过滤域名: ${data.blacklist_stats.unique_blocked_domains}个`;
        }

        // 更新趋势图表 - 修正数据显示
        const ctx = document.getElementById('trendChart').getContext('2d');

        // 销毁现有图表以避免重叠
        if (window.domainChart) {
            window.domainChart.destroy();
        }

        // 在更新图表数据之前设置容器高度
        const container = document.querySelector('.domain-stats-container');
        container.style.setProperty('--item-count', data.top_domains.length);

        window.domainChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.top_domains.map(domain => domain.domain),
                datasets: [{
                    label: '未命中',
                    data: data.top_domains.map(domain => domain.requests - domain.cache_hits),
                    backgroundColor: function (context) {
                        const chart = context.chart;
                        const { ctx, chartArea } = chart;
                        if (!chartArea) {
                            return 'rgba(37, 99, 235, 0.9)';
                        }
                        let gradientFill = ctx.createLinearGradient(0, 0, chartArea.width, 0);
                        gradientFill.addColorStop(0, 'rgba(37, 99, 235, 0.9)');
                        gradientFill.addColorStop(1, 'rgba(59, 130, 246, 0.9)');
                        return gradientFill;
                    },
                    borderWidth: 0,
                    borderRadius: 5,
                    barPercentage: 0.95,
                    categoryPercentage: 0.9
                }, {
                    label: '缓存命中',
                    data: data.top_domains.map(domain => domain.cache_hits),
                    backgroundColor: function (context) {
                        const chart = context.chart;
                        const { ctx, chartArea } = chart;
                        if (!chartArea) {
                            return 'rgba(46, 196, 182, 0.8)';
                        }
                        let gradientFill = ctx.createLinearGradient(0, 0, chartArea.width, 0);
                        gradientFill.addColorStop(0, 'rgba(46, 196, 182, 0.9)');
                        gradientFill.addColorStop(1, 'rgba(33, 158, 188, 0.9)');
                        return gradientFill;
                    },
                    borderWidth: 0,
                    borderRadius: 5,
                    barPercentage: 0.95,
                    categoryPercentage: 0.9
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 300,
                    easing: 'easeOutQuart'
                },
                plugins: {
                    legend: {
                        position: 'top',
                        align: 'end',
                        labels: {
                            boxWidth: 12,
                            usePointStyle: true,
                            padding: 15,
                            font: {
                                size: 12
                            }
                        }
                    },
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: true,
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        padding: 12,
                        bodySpacing: 4,
                        position: 'nearest',  // 改为nearest
                        events: ['mousemove'],
                        callbacks: {
                            title: function (tooltipItems) {
                                const item = tooltipItems[0];
                                // 未命中时只显示域名
                                if (item.datasetIndex === 0) {
                                    return item.label;
                                }
                                return item.label;
                            },
                            label: function (tooltipItem) {
                                const value = tooltipItem.raw;
                                if (tooltipItem.datasetIndex === 0) {
                                    return [`未命中: ${value}次`];
                                }

                                const domain = tooltipItem.label;
                                const domainData = data.top_domains.find(d => d.domain === domain);
                                if (!domainData || !domainData.details) return '';

                                let lines = [
                                    `总请求数: ${domainData.requests}`,
                                    `缓存命中: ${domainData.cache_hits}`,
                                    `命中率: ${((domainData.cache_hits / domainData.requests) * 100).toFixed(1)}%`,
                                    ''
                                ];

                                // ...existing tooltip code...

                                return lines;
                            },
                            labelColor: function (tooltipItem) {
                                // 返回对应数据集的颜色
                                const dataset = tooltipItem.dataset;
                                const color = tooltipItem.datasetIndex === 0 ?
                                    'rgba(37, 99, 235, 0.9)' :
                                    'rgba(46, 196, 182, 0.9)';
                                return {
                                    borderColor: color,
                                    backgroundColor: color
                                };
                            }
                        }
                    },
                    datalabels: {  // 添加数值标签
                        color: '#2c3e50',
                        font: {
                            weight: '600',
                            size: 11
                        },
                        anchor: 'end',
                        align: 'start',
                        formatter: (value, context) => {
                            return value;  // 直接显示数值
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,  // 启用堆叠
                        grid: {
                            display: false
                        },
                        ticks: {
                            precision: 0
                        }
                    },
                    y: {
                        stacked: true,  // 启用堆叠
                        grid: {
                            borderDash: [2, 4]
                        },
                        ticks: {
                            padding: 10,
                            callback: function (value) {
                                const label = this.getLabelForValue(value);
                                // 如果标签太长，截断并添加省略号
                                return label.length > 30 ? label.slice(0, 27) + '...' : label;
                            }
                        }
                    }
                }
            },
            plugins: [{
                id: 'customBarText',
                afterDraw: function (chart) {
                    const ctx = chart.ctx;
                    const activeElements = chart.getActiveElements();

                    chart.data.datasets.forEach((dataset, i) => {
                        const meta = chart.getDatasetMeta(i);
                        meta.data.forEach((bar, index) => {
                            const value = dataset.data[index];
                            if (value > 0) {
                                const position = bar.tooltipPosition();
                                const barWidth = bar.width;

                                // 检查当前条形图是否被hover
                                const isBarHovered = activeElements.some(element =>
                                    element.datasetIndex === i && element.index === index
                                );

                                // 如果当前条不是被hover的，就显示数字
                                if (!isBarHovered) {
                                    ctx.save();
                                    ctx.fillStyle = '#FFFFFF';
                                    ctx.font = '500 11px MiSans-VF';
                                    ctx.textAlign = 'left';
                                    ctx.textBaseline = 'middle';

                                    const text = value.toString();
                                    const textWidth = ctx.measureText(text).width;
                                    const minWidthForText = textWidth + 10;

                                    if (barWidth > minWidthForText) {
                                        const padding = 5;
                                        const x = position.x - textWidth - padding;
                                        const y = position.y;
                                        ctx.fillText(text, x, y);
                                    }
                                    ctx.restore();
                                }
                            }
                        });
                    });
                }
            }]
        });

        // 修改查询类型统计图表初始化
        const typeCtx = document.getElementById('queryTypeChart').getContext('2d');

        // 销毁现有图表以避免重叠
        if (window.queryTypeChart instanceof Chart) {
            window.queryTypeChart.destroy();
        }

        // 调整容器高度
        const typeContainer = typeCtx.canvas.closest('.domain-stats-container');
        typeContainer.style.setProperty('--item-count', data.query_types.length);

        window.queryTypeChart = new Chart(typeCtx, {
            type: 'bar',
            data: {
                labels: data.query_types.map(t => t.type),
                datasets: [{
                    label: '请求数',
                    data: data.query_types.map(t => t.count),
                    backgroundColor: 'rgba(67, 97, 238, 0.8)',
                    borderColor: 'rgba(67, 97, 238, 1)',
                    borderWidth: 1,
                    borderRadius: 5
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 200
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: function (context) {
                                return `请求数: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            precision: 0
                        }
                    },
                    y: {
                        grid: {
                            borderDash: [2, 4]
                        },
                        ticks: {
                            padding: 10
                        }
                    }
                }
            },
            plugins: [{
                id: 'customBarText',
                afterDraw: function (chart) {
                    const ctx = chart.ctx;
                    const activeElements = chart.getActiveElements();

                    chart.data.datasets.forEach((dataset, i) => {
                        const meta = chart.getDatasetMeta(i);
                        meta.data.forEach((bar, index) => {
                            const value = dataset.data[index];
                            if (value > 0) {
                                const position = bar.tooltipPosition();
                                const barWidth = bar.width;

                                // 检查当前条形图是否被hover
                                const isBarHovered = activeElements.some(element =>
                                    element.datasetIndex === i && element.index === index
                                );

                                // 如果当前条不是被hover的，就显示数字
                                if (!isBarHovered) {
                                    ctx.save();
                                    ctx.fillStyle = '#FFFFFF';
                                    ctx.font = '500 11px MiSans-VF';
                                    ctx.textAlign = 'left';
                                    ctx.textBaseline = 'middle';

                                    const text = value.toString();
                                    const textWidth = ctx.measureText(text).width;
                                    const minWidthForText = textWidth + 10;

                                    if (barWidth > minWidthForText) {
                                        const padding = 5;
                                        const x = position.x - textWidth - padding;
                                        const y = position.y;
                                        ctx.fillText(text, x, y);
                                    }
                                    ctx.restore();
                                }
                            }
                        });
                    });
                }
            }]
        });

        // 更新客户端统计
        const clients = data.top_clients || [];
        await updateClientStats(clients);

    } catch (error) {
        console.error('Error fetching data:', error);
    } finally {
        toggleLoading(false);
    }
}

// 改进WebSocket连接处理
let ws;
function connectWebSocket() {
    ws = new WebSocket('ws://' + window.location.host + '/ws');
    ws.onmessage = function (event) {
        if (event.data === 'update') {
            fetchData();
        }
    };
    ws.onclose = function () {
        // 连接关闭后自动重连
        setTimeout(connectWebSocket, 1000);
    };
}

// 取消定时刷新，改用WebSocket
document.addEventListener('DOMContentLoaded', () => {
    fetchData();
    connectWebSocket();
});

// 改进的复制提示函数
function showCopySuccess() {
    const toast = document.getElementById('copySuccess');
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 2000);
}