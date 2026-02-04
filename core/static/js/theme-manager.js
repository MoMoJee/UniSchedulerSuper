/**
 * 主题管理器
 * 负责管理应用的主题切换 (浅色/深色/跟随系统)
 */
class ThemeManager {
    constructor() {
        this.themes = [
            'light', 'dark', 'auto',
            'china-red', 'warm-pastel', 'cool-pastel', 'macaron', 'dopamine',
            'forest', 'sunset', 'ocean', 'sakura', 'cyberpunk'
        ];
        this.currentTheme = 'light';
        this.systemTheme = 'light';
        this.useGoldTheme = false; // 金色主题开关
        this.mediaQuery = null;
    }

    /**
     * 初始化主题管理器
     */
    init() {
        console.log('🎨 主题管理器初始化...');
        
        // 监听系统主题变化
        this.watchSystemTheme();
        
        // 从用户设置加载主题
        const savedTheme = window.userSettings?.theme || 'light';
        this.useGoldTheme = window.userSettings?.use_gold_theme || false;
        this.applyTheme(savedTheme, false); // false表示不保存,因为是从设置加载的
        
        console.log('✅ 主题管理器初始化完成,当前主题:', this.currentTheme, '金色主题:', this.useGoldTheme);
    }

    /**
     * 应用主题
     * @param {string} theme - 主题名称 ('light', 'dark', 'auto')
     * @param {boolean} save - 是否保存到设置,默认true
     */
    applyTheme(theme, save = true) {
        if (!this.themes.includes(theme)) {
            console.warn(`未知主题: ${theme}, 使用默认主题 light`);
            theme = 'light';
        }

        this.currentTheme = theme;
        
        let effectiveTheme;
        if (theme === 'auto') {
            // 跟随系统
            effectiveTheme = this.systemTheme;
            console.log(`应用自动主题,跟随系统: ${effectiveTheme}`);
        } else {
            // 手动指定
            effectiveTheme = theme;
            console.log(`应用手动主题: ${effectiveTheme}`);
        }
        
        // 如果启用了金色主题，并且当前是浅色或深色主题，替换为金色版本
        if (this.useGoldTheme && (effectiveTheme === 'light' || effectiveTheme === 'dark')) {
            effectiveTheme = effectiveTheme === 'light' ? 'platinum-light' : 'platinum-dark';
            console.log(`金色主题已启用,切换到: ${effectiveTheme}`);
        }
        
        // 设置HTML属性
        document.documentElement.setAttribute('data-theme', effectiveTheme);
        
        // 添加过渡类以实现平滑切换
        document.documentElement.classList.add('theme-transitioning');
        setTimeout(() => {
            document.documentElement.classList.remove('theme-transitioning');
        }, 300);
        
        // 更新FullCalendar
        this.updateFullCalendarTheme(effectiveTheme);
        
        // 触发自定义事件
        window.dispatchEvent(new CustomEvent('themechange', { 
            detail: { theme: effectiveTheme, mode: theme } 
        }));
        
        // 保存到设置
        if (save) {
            this.saveTheme(theme);
        }
    }

    /**
     * 监听系统主题变化
     */
    watchSystemTheme() {
        // 检测系统主题
        this.mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        this.systemTheme = this.mediaQuery.matches ? 'dark' : 'light';
        
        console.log('系统主题:', this.systemTheme);
        
        // 监听系统主题变化
        this.mediaQuery.addEventListener('change', (e) => {
            const newSystemTheme = e.matches ? 'dark' : 'light';
            console.log('系统主题变化:', this.systemTheme, '→', newSystemTheme);
            
            this.systemTheme = newSystemTheme;
            
            // 如果当前是auto模式,重新应用主题
            if (this.currentTheme === 'auto') {
                this.applyTheme('auto', false);
            }
        });
    }

    /**
     * 更新FullCalendar主题
     * @param {string} theme - 有效主题 ('light' 或 'dark')
     */
    updateFullCalendarTheme(theme) {
        const calendar = window.eventManager?.calendar;
        if (calendar) {
            // FullCalendar会自动响应CSS变量的变化
            // 这里可以触发重新渲染以确保样式正确
            try {
                calendar.render();
                console.log('FullCalendar主题已更新');
            } catch (error) {
                console.warn('更新FullCalendar主题失败:', error);
            }
        }
    }

    /**
     * 保存主题到设置
     * @param {string} theme - 主题名称
     */
    saveTheme(theme) {
        // 更新全局设置
        if (window.userSettings) {
            window.userSettings.theme = theme;
            window.userSettings.use_gold_theme = this.useGoldTheme;
        }
        
        // 通过设置管理器保存
        if (window.settingsManager) {
            window.settingsManager.updateSetting('userPreferences', 'theme', theme);
            window.settingsManager.updateSetting('userPreferences', 'use_gold_theme', this.useGoldTheme);
        }
        
        console.log('主题已保存:', theme, '金色主题:', this.useGoldTheme);
    }

    /**
     * 切换金色主题
     * @param {boolean} enabled - 是否启用金色主题
     */
    toggleGoldTheme(enabled) {
        this.useGoldTheme = enabled;
        console.log('金色主题切换:', enabled);
        
        // 重新应用当前主题
        this.applyTheme(this.currentTheme);
    }

    /**
     * 切换主题 (循环: light → dark → auto → light)
     */
    toggle() {
        const currentIndex = this.themes.indexOf(this.currentTheme);
        const nextTheme = this.themes[(currentIndex + 1) % this.themes.length];
        
        console.log('切换主题:', this.currentTheme, '→', nextTheme);
        this.applyTheme(nextTheme);
        
        return nextTheme;
    }

    /**
     * 获取当前主题
     * @returns {string} 当前主题名称
     */
    getCurrentTheme() {
        return this.currentTheme;
    }

    /**
     * 获取有效主题 (auto会解析为实际的light/dark)
     * @returns {string} 有效主题名称
     */
    getEffectiveTheme() {
        if (this.currentTheme === 'auto') {
            return this.systemTheme;
        }
        return this.currentTheme;
    }

    /**
     * 获取主题显示名称
     * @param {string} theme - 主题名称
     * @returns {string} 显示名称
     */
    getThemeDisplayName(theme) {
        const names = {
            'light': '浅色模式',
            'dark': '深色模式',
            'auto': '跟随系统',
            'china-red': '中国红',
            'warm-pastel': '淡暖色',
            'cool-pastel': '淡冷色',
            'macaron': '马卡龙',
            'dopamine': '多巴胺',
            'forest': '森林',
            'sunset': '日落',
            'ocean': '海洋',
            'sakura': '樱花',
            'cyberpunk': '赛博朋克'
        };
        return names[theme] || theme;
    }

    /**
     * 获取主题图标
     * @param {string} theme - 主题名称
     * @returns {string} Font Awesome图标类名
     */
    getThemeIcon(theme) {
        const icons = {
            'light': 'fa-sun',
            'dark': 'fa-moon',
            'auto': 'fa-circle-half-stroke',
            'china-red': 'fa-flag',
            'warm-pastel': 'fa-heart',
            'cool-pastel': 'fa-snowflake',
            'macaron': 'fa-cookie',
            'dopamine': 'fa-bolt',
            'forest': 'fa-tree',
            'sunset': 'fa-cloud-sun',
            'ocean': 'fa-water',
            'sakura': 'fa-spa',
            'cyberpunk': 'fa-robot'
        };
        return icons[theme] || 'fa-circle';
    }
}

// 创建全局主题管理器实例
window.themeManager = new ThemeManager();
