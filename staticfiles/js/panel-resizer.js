// 面板调节器管理类
class PanelResizer {
    constructor() {
        this.isResizing = false;
        this.currentHandle = null;
        this.startX = 0;
        this.startWidths = {};
        this.minWidthPercent = 15;
        this.maxWidthPercent = 70;
        
        this.init();
    }

    init() {
        // 绑定调节器事件
        document.querySelectorAll('.resize-handle').forEach(handle => {
            handle.addEventListener('mousedown', this.startResize.bind(this));
        });

        // 绑定全局事件
        document.addEventListener('mousemove', this.doResize.bind(this));
        document.addEventListener('mouseup', this.stopResize.bind(this));
        
        // 防止选择文本
        document.addEventListener('selectstart', (e) => {
            if (this.isResizing) {
                e.preventDefault();
            }
        });
    }

    startResize(e) {
        e.preventDefault();
        this.isResizing = true;
        this.currentHandle = e.target;
        this.startX = e.clientX;

        // 记录当前宽度
        const container = document.querySelector('.main-container');
        const leftPanel = container.querySelector('.left-panel');
        const centerPanel = container.querySelector('.center-panel');
        const rightPanel = container.querySelector('.right-panel');

        this.startWidths = {
            left: leftPanel.offsetWidth,
            center: centerPanel.offsetWidth,
            right: rightPanel.offsetWidth,
            container: container.offsetWidth
        };

        // 添加调节中的样式
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        this.currentHandle.classList.add('resizing');
        
        console.log('开始拖动调节器', this.startWidths); // 调试信息
    }

    doResize(e) {
        if (!this.isResizing) return;

        e.preventDefault();
        const deltaX = e.clientX - this.startX;
        const container = document.querySelector('.main-container');
        const leftPanel = container.querySelector('.left-panel');
        const centerPanel = container.querySelector('.center-panel');
        const rightPanel = container.querySelector('.right-panel');

        if (this.currentHandle.classList.contains('left-resize')) {
            // 调节左侧面板和中央面板
            const newLeftWidth = this.startWidths.left + deltaX;
            const newCenterWidth = this.startWidths.center - deltaX;

            // 检查最小/最大宽度限制
            const leftPercent = (newLeftWidth / this.startWidths.container) * 100;
            const centerPercent = (newCenterWidth / this.startWidths.container) * 100;

            if (leftPercent >= this.minWidthPercent && leftPercent <= 35 &&
                centerPercent >= 30 && centerPercent <= this.maxWidthPercent) {
                // 使用flex-basis而不是width
                leftPanel.style.flexBasis = `${leftPercent}%`;
                centerPanel.style.flexBasis = `${centerPercent}%`;
            }
        } else if (this.currentHandle.classList.contains('right-resize')) {
            // 调节中央面板和右侧面板
            const newCenterWidth = this.startWidths.center + deltaX;
            const newRightWidth = this.startWidths.right - deltaX;

            // 检查最小/最大宽度限制
            const centerPercent = (newCenterWidth / this.startWidths.container) * 100;
            const rightPercent = (newRightWidth / this.startWidths.container) * 100;

            if (centerPercent >= 30 && centerPercent <= this.maxWidthPercent &&
                rightPercent >= 20 && rightPercent <= 50) {
                // 使用flex-basis而不是width
                centerPanel.style.flexBasis = `${centerPercent}%`;
                rightPanel.style.flexBasis = `${rightPercent}%`;
            }
        }
    }

    stopResize() {
        if (!this.isResizing) return;

        this.isResizing = false;
        
        // 移除调节中的样式
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        if (this.currentHandle) {
            this.currentHandle.classList.remove('resizing');
        }
        
        this.currentHandle = null;

        // 触发日历重绘
        if (window.eventManager && window.eventManager.calendar) {
            setTimeout(() => {
                window.eventManager.calendar.updateSize();
            }, 100);
        }
        
        // 保存当前布局到设置管理器
        if (window.settingsManager) {
            const leftPanel = document.querySelector('.left-panel');
            const centerPanel = document.querySelector('.center-panel');
            const rightPanel = document.querySelector('.right-panel');
            
            if (leftPanel && centerPanel && rightPanel) {
                const leftPercent = parseFloat(leftPanel.style.flexBasis);
                const centerPercent = parseFloat(centerPanel.style.flexBasis);
                const rightPercent = parseFloat(rightPanel.style.flexBasis);
                
                window.settingsManager.onPanelLayoutChange(leftPercent, centerPercent, rightPercent);
            }
        }
        
        console.log('停止拖动调节器'); // 调试信息
    }

    // 重置面板宽度到默认值
    resetToDefault() {
        const leftPanel = document.querySelector('.left-panel');
        const centerPanel = document.querySelector('.center-panel');
        const rightPanel = document.querySelector('.right-panel');

        // 使用flex-basis重置
        leftPanel.style.flexBasis = '20%';
        centerPanel.style.flexBasis = '50%';
        rightPanel.style.flexBasis = '30%';

        // 触发日历重绘
        if (window.eventManager && window.eventManager.calendar) {
            setTimeout(() => {
                window.eventManager.calendar.updateSize();
            }, 100);
        }
    }

    // 设置面板布局（从设置管理器调用）
    setLayout(leftPercent, centerPercent, rightPercent) {
        const leftPanel = document.querySelector('.left-panel');
        const centerPanel = document.querySelector('.center-panel');
        const rightPanel = document.querySelector('.right-panel');

        if (leftPanel && centerPanel && rightPanel) {
            leftPanel.style.flexBasis = `${leftPercent}%`;
            centerPanel.style.flexBasis = `${centerPercent}%`;
            rightPanel.style.flexBasis = `${rightPercent}%`;

            // 触发日历重绘
            if (window.eventManager && window.eventManager.calendar) {
                setTimeout(() => {
                    window.eventManager.calendar.updateSize();
                }, 100);
            }

            console.log(`应用面板布局: ${leftPercent}% / ${centerPercent}% / ${rightPercent}%`);
        }
    }
}

// 面板调节器类已定义，实例将在HTML中创建

// 窗口大小改变时重新计算
window.addEventListener('resize', () => {
    if (window.eventManager && window.eventManager.calendar) {
        setTimeout(() => {
            window.eventManager.calendar.updateSize();
        }, 100);
    }
});
