// 容器查询 Polyfill
// 为不支持CSS Container Queries的浏览器提供后备支持

(function() {
    'use strict';
    
    // 检查浏览器是否支持容器查询
    const supportsContainerQueries = 'container' in document.documentElement.style;
    
    if (supportsContainerQueries) {
        console.log('浏览器原生支持容器查询，无需polyfill');
        return;
    }
    
    console.log('浏览器不支持容器查询，启用polyfill');
    
    // ResizeObserver用于监测容器大小变化
    if (!window.ResizeObserver) {
        console.warn('浏览器不支持ResizeObserver，容器查询polyfill将不工作');
        return;
    }
    
    // 监测的容器选择器
    const containerSelectors = ['.todo-list', '.reminder-list'];
    const narrowThreshold = 450; // px
    
    // 创建ResizeObserver实例
    const resizeObserver = new ResizeObserver(entries => {
        entries.forEach(entry => {
            const container = entry.target;
            const width = entry.contentRect.width;
            
            // 根据宽度添加或移除.narrow类
            if (width < narrowThreshold) {
                if (!container.classList.contains('narrow')) {
                    container.classList.add('narrow');
                    console.log(`容器 ${container.className} 宽度 ${width}px < ${narrowThreshold}px, 添加.narrow类`);
                }
            } else {
                if (container.classList.contains('narrow')) {
                    container.classList.remove('narrow');
                    console.log(`容器 ${container.className} 宽度 ${width}px >= ${narrowThreshold}px, 移除.narrow类`);
                }
            }
        });
    });
    
    // 初始化函数
    function initContainerQueryPolyfill() {
        containerSelectors.forEach(selector => {
            const containers = document.querySelectorAll(selector);
            containers.forEach(container => {
                // 开始观察容器
                resizeObserver.observe(container);
                console.log(`开始观察容器: ${selector}`);
                
                // 立即触发一次检查
                const width = container.offsetWidth;
                if (width < narrowThreshold) {
                    container.classList.add('narrow');
                } else {
                    container.classList.remove('narrow');
                }
            });
        });
    }
    
    // DOM加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initContainerQueryPolyfill);
    } else {
        initContainerQueryPolyfill();
    }
    
    // 同时监听窗口大小变化（用于响应式面板调整）
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            // 重新检查所有容器
            containerSelectors.forEach(selector => {
                const containers = document.querySelectorAll(selector);
                containers.forEach(container => {
                    const width = container.offsetWidth;
                    if (width < narrowThreshold) {
                        container.classList.add('narrow');
                    } else {
                        container.classList.remove('narrow');
                    }
                });
            });
        }, 100); // 防抖100ms
    });
    
    // 暴露到全局，供其他模块调用
    window.containerQueryPolyfill = {
        refresh: initContainerQueryPolyfill,
        threshold: narrowThreshold
    };
    
})();
