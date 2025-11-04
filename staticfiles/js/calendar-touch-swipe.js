/**
 * 日历触屏滑动支持模块
 * 为 FullCalendar 添加左右滑动切换上/下一个时间段的功能
 * 
 * 使用方法：
 * const calendarSwipe = new CalendarTouchSwipe(calendarInstance);
 */

class CalendarTouchSwipe {
    constructor(calendar) {
        this.calendar = calendar;
        this.touchStartX = 0;
        this.touchStartY = 0;
        this.touchEndX = 0;
        this.touchEndY = 0;
        this.isSwiping = false;
        this.calendarEl = null;
        this.isAnimating = false;
        this.interactionsDisabled = false;  // 标记是否已禁用交互
        
        // 配置参数
        this.config = {
            minSwipeDistance: 50,        // 最小滑动距离（像素）
            maxVerticalDistance: 100,    // 垂直方向最大偏移（像素），避免与滚动冲突
            swipeAngleThreshold: 30,     // 滑动角度阈值（度），确保是水平滑动
            followDamping: 0.6,          // 跟随阻尼系数（0-1），提高到0.6让跟随更直接流畅
            maxFollowDistance: 120,      // 最大跟随距离（像素），稍微增加让滑动更自由
            bounceBackDuration: 200,     // 回弹动画时长（毫秒），快速回弹
            switchDuration: 200          // 切换动画时长（毫秒），快速切换消除等待感
        };
        
        this.init();
    }
    
    /**
     * 初始化触摸事件监听
     */
    init() {
        this.calendarEl = document.getElementById('calendar');
        if (!this.calendarEl) {
            console.warn('未找到日历元素，无法启用触屏滑动');
            return;
        }
        
        // 使用被动监听器提升性能
        this.calendarEl.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: true });
        this.calendarEl.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        this.calendarEl.addEventListener('touchend', this.handleTouchEnd.bind(this), { passive: true });
        
        console.log('✅ 日历触屏滑动功能已启用');
    }
    
    /**
     * 处理触摸开始事件
     */
    handleTouchStart(event) {
        // 只处理单指触摸
        if (event.touches.length !== 1) {
            return;
        }
        
        const touch = event.touches[0];
        this.touchStartX = touch.clientX;
        this.touchStartY = touch.clientY;
        this.isSwiping = false;
        this.interactionsDisabled = false;  // 重置禁用标志
        
        // 检查触摸点是否在日历的可视区域内
        const target = event.target;
        const isInCalendarArea = this.isInCalendarViewArea(target);
        
        if (!isInCalendarArea) {
            // 如果触摸点在按钮、标题栏等区域，不处理滑动
            this.touchStartX = 0;
            this.touchStartY = 0;
            return;
        }
        
        // 移除之前的过渡效果，准备实时跟随
        if (this.calendarEl) {
            this.calendarEl.style.transition = 'none';
        }
        
        // 不要在这里禁用交互，等确认是水平滑动后再禁用
    }
    
    /**
     * 处理触摸移动事件
     */
    handleTouchMove(event) {
        if (!this.touchStartX || !this.touchStartY) {
            return;
        }
        
        // 只处理单指触摸
        if (event.touches.length !== 1) {
            return;
        }
        
        const touch = event.touches[0];
        this.touchEndX = touch.clientX;
        this.touchEndY = touch.clientY;
        
        const deltaX = this.touchEndX - this.touchStartX;
        const deltaY = this.touchEndY - this.touchStartY;
        
        // 计算滑动角度
        const angle = Math.abs(Math.atan2(deltaY, deltaX) * 180 / Math.PI);
        const isHorizontalSwipe = angle < this.config.swipeAngleThreshold || 
                                  angle > (180 - this.config.swipeAngleThreshold);
        
        // 如果是水平滑动，应用实时跟随效果
        if (isHorizontalSwipe && Math.abs(deltaX) > 10) {
            this.isSwiping = true;
            
            // 第一次检测到水平滑动时，立即禁用交互
            if (!this.interactionsDisabled) {
                this.disableCalendarInteractions();
                this.interactionsDisabled = true;
                console.log('🔒 检测到水平滑动，已禁用日历交互');
            }
            
            // 阻止默认行为（避免页面左右滚动）
            if (Math.abs(deltaX) > Math.abs(deltaY)) {
                event.preventDefault();
            }
            
            // 应用实时跟随效果
            this.applyFollowEffect(deltaX);
        }
    }
    
    /**
     * 应用实时跟随效果
     * @param {number} deltaX - 水平位移
     */
    applyFollowEffect(deltaX) {
        if (!this.calendarEl || this.isAnimating) {
            return;
        }
        
        // 使用阻尼系数计算实际位移，并限制最大跟随距离
        const dampedDistance = deltaX * this.config.followDamping;
        const clampedDistance = Math.max(
            -this.config.maxFollowDistance,
            Math.min(this.config.maxFollowDistance, dampedDistance)
        );
        
        // 计算透明度变化（滑动越远，透明度越低，但变化更微妙）
        const opacityReduction = (Math.abs(clampedDistance) / this.config.maxFollowDistance) * 0.1;
        const opacity = 1 - opacityReduction;
        
        // 应用 transform 和透明度
        this.calendarEl.style.transform = `translateX(${clampedDistance}px)`;
        this.calendarEl.style.opacity = opacity;
        
        // 显示方向提示
        this.showDirectionHint(deltaX);
    }
    
    /**
     * 显示方向提示
     * @param {number} deltaX - 水平位移
     */
    showDirectionHint(deltaX) {
        const direction = deltaX > 0 ? 'prev' : 'next';
        const absDistance = Math.abs(deltaX);
        
        // 只有当滑动距离接近触发阈值时才显示提示
        if (absDistance > this.config.minSwipeDistance * 0.6) {
            this.showSwipeIndicator(direction, true);
        } else {
            this.hideSwipeIndicator();
        }
    }
    
    /**
     * 处理触摸结束事件
     */
    handleTouchEnd(event) {
        if (!this.touchStartX || !this.touchStartY) {
            return;
        }
        
        // 确保有 touchEnd 坐标（如果 touchMove 没有触发）
        if (event.changedTouches && event.changedTouches.length > 0) {
            const touch = event.changedTouches[0];
            this.touchEndX = touch.clientX;
            this.touchEndY = touch.clientY;
        }
        
        const deltaX = this.touchEndX - this.touchStartX;
        const deltaY = this.touchEndY - this.touchStartY;
        
        // 计算水平和垂直距离
        const horizontalDistance = Math.abs(deltaX);
        const verticalDistance = Math.abs(deltaY);
        
        // 判断是否是有效的水平滑动
        const isValidSwipe = 
            horizontalDistance > this.config.minSwipeDistance &&
            verticalDistance < this.config.maxVerticalDistance &&
            horizontalDistance > verticalDistance; // 水平距离要大于垂直距离
        
        if (isValidSwipe && this.calendar) {
            // 执行切换动画
            this.performSwitch(deltaX > 0 ? 'prev' : 'next');
        } else {
            // 滑动距离不足，执行回弹动画
            this.bounceBack();
            // 如果禁用了交互，回弹后立即恢复
            if (this.interactionsDisabled) {
                this.enableCalendarInteractions();
            }
        }
        
        // 重置状态
        this.touchStartX = 0;
        this.touchStartY = 0;
        this.touchEndX = 0;
        this.touchEndY = 0;
        this.isSwiping = false;
        // 注意：不在这里重置 interactionsDisabled，因为可能还在动画中
    }
    
    /**
     * 执行切换动画
     * @param {string} direction - 'prev' 或 'next'
     */
    performSwitch(direction) {
        if (!this.calendarEl || this.isAnimating) {
            return;
        }
        
        this.isAnimating = true;
        const isPrev = direction === 'prev';
        
        // 第一阶段：滑出动画 - 使用ease-out让滑出更快速流畅
        this.calendarEl.style.transition = `transform ${this.config.switchDuration}ms cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity ${this.config.switchDuration}ms ease-out`;
        
        // 向右滑动查看上一个时间段，日历向右滑出
        // 向左滑动查看下一个时间段，日历向左滑出
        const slideDistance = isPrev ? '120px' : '-120px';
        this.calendarEl.style.transform = `translateX(${slideDistance})`;
        this.calendarEl.style.opacity = '0.6';
        
        // 显示切换指示器
        this.showSwipeIndicator(direction, false);
        
        console.log(`🔄 ${isPrev ? '向右' : '向左'}滑动，切换到${isPrev ? '上' : '下'}一个时间段`);
        
        // 等待滑出动画完成后切换日历内容
        setTimeout(() => {
            // 执行日历切换
            if (isPrev) {
                this.calendar.prev();
            } else {
                this.calendar.next();
            }
            
            // 从相反方向滑入
            const slideInFrom = isPrev ? '-100px' : '100px';
            this.calendarEl.style.transition = 'none';
            this.calendarEl.style.transform = `translateX(${slideInFrom})`;
            this.calendarEl.style.opacity = '0.6';
            
            // 强制重排
            this.calendarEl.offsetHeight;
            
            // 第二阶段：滑入动画 - 使用ease-out让滑入更自然
            requestAnimationFrame(() => {
                this.calendarEl.style.transition = `transform ${this.config.switchDuration}ms cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity ${this.config.switchDuration}ms ease-out`;
                this.calendarEl.style.transform = 'translateX(0)';
                this.calendarEl.style.opacity = '1';
                
                // 动画结束后清理
                setTimeout(() => {
                    this.resetCalendarStyle();
                    this.isAnimating = false;
                    // 恢复 FullCalendar 交互功能
                    this.enableCalendarInteractions();
                }, this.config.switchDuration);
            });
        }, this.config.switchDuration * 0.6);
    }
    
    /**
     * 回弹动画（滑动距离不足时）
     */
    bounceBack() {
        if (!this.calendarEl) {
            return;
        }
        
        this.hideSwipeIndicator();
        
        // 平滑回弹到原位 - 使用更快速的缓动曲线
        this.calendarEl.style.transition = `transform ${this.config.bounceBackDuration}ms cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity ${this.config.bounceBackDuration}ms ease-out`;
        this.calendarEl.style.transform = 'translateX(0)';
        this.calendarEl.style.opacity = '1';
        
        // 动画结束后清理
        setTimeout(() => {
            this.resetCalendarStyle();
        }, this.config.bounceBackDuration);
    }
    
    /**
     * 重置日历样式
     */
    resetCalendarStyle() {
        if (!this.calendarEl) {
            return;
        }
        
        this.calendarEl.style.transition = '';
        this.calendarEl.style.transform = '';
        this.calendarEl.style.opacity = '';
    }
    
    /**
     * 检查触摸点是否在日历的主要视图区域内
     * 避免在按钮、标题栏等区域触发滑动
     */
    isInCalendarViewArea(target) {
        // 检查是否在日历容器内
        const calendarEl = document.getElementById('calendar');
        if (!calendarEl || !calendarEl.contains(target)) {
            return false;
        }
        
        // 排除以下区域：
        // 1. 按钮和工具栏
        if (target.closest('.fc-toolbar, .fc-button, button, a')) {
            return false;
        }
        
        // 2. 筛选下拉菜单
        if (target.closest('#calendarFilterDropdown, .calendar-filter-dropdown')) {
            return false;
        }
        
        // 3. 模态框
        if (target.closest('.modal')) {
            return false;
        }
        
        // 其他区域都允许滑动
        return true;
    }
    
    /**
     * 显示滑动指示器（可选的视觉反馈）
     * @param {string} direction - 'prev' 或 'next'
     * @param {boolean} persistent - 是否持续显示（不自动消失）
     */
    showSwipeIndicator(direction, persistent = false) {
        // 移除现有的指示器
        this.hideSwipeIndicator();
        
        // 创建一个临时的指示器元素
        const indicator = document.createElement('div');
        indicator.className = 'swipe-indicator';
        indicator.id = 'calendar-swipe-indicator';
        indicator.innerHTML = direction === 'prev' 
            ? '<i class="fas fa-chevron-left"></i>' 
            : '<i class="fas fa-chevron-right"></i>';
        
        // 设置样式
        indicator.style.cssText = `
            position: fixed;
            top: 50%;
            ${direction === 'prev' ? 'left: 20px;' : 'right: 20px;'}
            transform: translateY(-50%);
            background: rgba(0, 123, 255, 0.85);
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            z-index: 9999;
            pointer-events: none;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            transition: opacity 0.2s ease, transform 0.2s ease;
        `;
        
        // 如果不是持续显示模式，添加淡出动画
        if (!persistent) {
            indicator.style.animation = 'swipeIndicatorFade 0.6s ease-out';
        }
        
        document.body.appendChild(indicator);
        
        // 如果不是持续显示，动画结束后移除
        if (!persistent) {
            setTimeout(() => {
                indicator.remove();
            }, 600);
        }
    }
    
    /**
     * 隐藏滑动指示器
     */
    hideSwipeIndicator() {
        const existingIndicator = document.getElementById('calendar-swipe-indicator');
        if (existingIndicator) {
            existingIndicator.remove();
        }
    }
    
    /**
     * 禁用 FullCalendar 的交互功能
     * 防止滑动时触发 select、eventDrop、eventResize 等事件
     */
    disableCalendarInteractions() {
        if (!this.calendar) {
            return;
        }
        
        // 保存原始配置
        if (!this.originalCalendarOptions) {
            this.originalCalendarOptions = {
                editable: this.calendar.getOption('editable'),
                selectable: this.calendar.getOption('selectable'),
                eventStartEditable: this.calendar.getOption('eventStartEditable'),
                eventDurationEditable: this.calendar.getOption('eventDurationEditable')
            };
        }
        
        // 临时禁用交互
        this.calendar.setOption('editable', false);
        this.calendar.setOption('selectable', false);
        this.calendar.setOption('eventStartEditable', false);
        this.calendar.setOption('eventDurationEditable', false);
    }
    
    /**
     * 恢复 FullCalendar 的交互功能
     */
    enableCalendarInteractions() {
        if (!this.calendar || !this.originalCalendarOptions) {
            return;
        }
        
        // 延迟恢复，避免松手瞬间触发点击事件
        setTimeout(() => {
            this.calendar.setOption('editable', this.originalCalendarOptions.editable);
            this.calendar.setOption('selectable', this.originalCalendarOptions.selectable);
            this.calendar.setOption('eventStartEditable', this.originalCalendarOptions.eventStartEditable);
            this.calendar.setOption('eventDurationEditable', this.originalCalendarOptions.eventDurationEditable);
            
            // 重置禁用标志
            this.interactionsDisabled = false;
            console.log('🔓 已恢复日历交互');
        }, 100);
    }
    
    /**
     * 销毁滑动监听器
     */
    destroy() {
        const calendarEl = document.getElementById('calendar');
        if (calendarEl) {
            calendarEl.removeEventListener('touchstart', this.handleTouchStart);
            calendarEl.removeEventListener('touchmove', this.handleTouchMove);
            calendarEl.removeEventListener('touchend', this.handleTouchEnd);
        }
        
        // 确保恢复交互功能
        this.enableCalendarInteractions();
        
        console.log('日历触屏滑动功能已禁用');
    }
}

// 添加滑动指示器的CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes swipeIndicatorFade {
        0% {
            opacity: 0;
            transform: translateY(-50%) scale(0.5);
        }
        20% {
            opacity: 1;
            transform: translateY(-50%) scale(1.1);
        }
        40% {
            transform: translateY(-50%) scale(1);
        }
        100% {
            opacity: 0;
            transform: translateY(-50%) scale(0.8);
        }
    }
    
    .swipe-indicator {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
`;
document.head.appendChild(style);

// 导出类供外部使用
window.CalendarTouchSwipe = CalendarTouchSwipe;
