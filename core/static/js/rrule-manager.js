// 重复事件RRule管理模块
class RRuleManager {
    constructor() {
        this.init();
    }

    init() {
        this.setupEventListeners();
    }

    // 设置事件监听器
    setupEventListeners() {
        // 重复事件切换监听器
        const createRepeatCheckbox = document.getElementById('newEventIsRecurring');
        const editRepeatCheckbox = document.getElementById('eventIsRecurring');

        if (createRepeatCheckbox) {
            createRepeatCheckbox.addEventListener('change', () => {
                this.toggleRepeatOptions('create');
            });
        }

        if (editRepeatCheckbox) {
            editRepeatCheckbox.addEventListener('change', () => {
                this.toggleRepeatOptions('edit');
            });
        }

        // 频率变化监听器
        this.setupFrequencyListeners();
        this.setupEndConditionListeners();
        this.setupMonthlyTypeListeners();
        this.setupWeekdayListeners();
    }

    // 设置频率选择监听器
    setupFrequencyListeners() {
        ['create', 'edit'].forEach(mode => {
            const prefix = mode === 'create' ? 'newEvent' : 'event';
            const freqSelect = document.getElementById(`${prefix}Freq`);
            
            if (freqSelect) {
                freqSelect.addEventListener('change', () => {
                    this.updateFrequencyOptions(mode);
                    this.updateRulePreview(mode);
                });
            }

            // 间隔输入监听器
            const intervalInput = document.getElementById(`${prefix}Interval`);
            if (intervalInput) {
                intervalInput.addEventListener('input', () => {
                    this.updateRulePreview(mode);
                });
            }
        });
    }

    // 设置结束条件监听器
    setupEndConditionListeners() {
        ['create', 'edit'].forEach(mode => {
            const prefix = mode === 'create' ? 'newEvent' : 'editEvent';
            const endSelect = document.getElementById(`${prefix}EndType`);
            
            if (endSelect) {
                endSelect.addEventListener('change', () => {
                    this.updateEndConditionFields(mode);
                    this.updateRulePreview(mode);
                });
            } else {
                console.warn(`End condition select not found: ${prefix}EndType`);
            }

            // 次数和截止日期输入监听器
            const countInput = document.getElementById(`${prefix}Count`);
            const untilInput = document.getElementById(`${prefix}Until`);

            if (countInput) {
                countInput.addEventListener('input', () => {
                    this.updateRulePreview(mode);
                });
            }

            if (untilInput) {
                untilInput.addEventListener('change', () => {
                    this.updateRulePreview(mode);
                });
            }
        });
    }

    // 设置月度重复类型监听器
    setupMonthlyTypeListeners() {
        ['create', 'edit'].forEach(mode => {
            const prefix = mode === 'create' ? 'newEvent' : 'event';
            
            if (mode === 'create') {
                // 新建模式：监听select元素
                const monthlyTypeSelect = document.getElementById(`${prefix}MonthlyType`);
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.addEventListener('change', () => {
                        this.updateEventMonthlyOptions(mode);
                    });
                }
            } else {
                // 编辑模式：监听radio buttons
                const monthlyRadioByDate = document.getElementById('editEventMonthlyByDate');
                const monthlyRadioByWeek = document.getElementById('editEventMonthlyByWeek');
                
                if (monthlyRadioByDate) {
                    monthlyRadioByDate.addEventListener('change', () => {
                        if (monthlyRadioByDate.checked) {
                            this.updateEventMonthlyOptions(mode);
                        }
                    });
                }
                
                if (monthlyRadioByWeek) {
                    monthlyRadioByWeek.addEventListener('change', () => {
                        if (monthlyRadioByWeek.checked) {
                            this.updateEventMonthlyOptions(mode);
                        }
                    });
                }
            }
            
            // 月重复相关选择器的监听器
            const monthlyDateSelect = document.getElementById(`${prefix}MonthlyDate`);
            const monthlyWeekSelect = document.getElementById(`${prefix}MonthlyWeek`);
            const monthlyWeekdaySelect = document.getElementById(`${prefix}MonthlyWeekday`);
            
            if (monthlyDateSelect) {
                monthlyDateSelect.addEventListener('change', () => {
                    this.updateRulePreview(mode);
                });
            }
            
            if (monthlyWeekSelect) {
                monthlyWeekSelect.addEventListener('change', () => {
                    this.updateRulePreview(mode);
                });
            }
            
            if (monthlyWeekdaySelect) {
                monthlyWeekdaySelect.addEventListener('change', () => {
                    this.updateRulePreview(mode);
                });
            }
        });
    }

    // 设置星期按钮监听器
    setupWeekdayListeners() {
        ['create', 'edit'].forEach(mode => {
            const prefix = mode === 'create' ? 'newEvent' : 'event';
            const weekdayContainer = document.getElementById(`${prefix}WeekdaysContainer`);
            if (weekdayContainer) {
                const weekdayButtons = weekdayContainer.querySelectorAll('.weekday-btn');
                weekdayButtons.forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.preventDefault();
                        this.toggleWeekdayButton(btn);
                        this.updateRulePreview(mode);
                    });
                });
            }
        });
    }

    // 切换重复选项显示
    toggleRepeatOptions(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'event';
        const checkbox = document.getElementById(`${prefix}IsRecurring`);
        const options = document.getElementById(`${prefix}RecurringOptions`);

        if (checkbox && options) {
            if (checkbox.checked) {
                options.style.display = 'block';
                this.updateFrequencyOptions(mode);
                this.updateRulePreview(mode);
            } else {
                options.style.display = 'none';
            }
        }
    }

    // 切换星期按钮状态
    toggleWeekdayButton(button) {
        button.classList.toggle('active');
        if (button.classList.contains('active')) {
            button.classList.remove('btn-outline-primary');
            button.classList.add('btn-primary');
        } else {
            button.classList.remove('btn-primary');
            button.classList.add('btn-outline-primary');
        }
    }

    // 更新频率相关选项
    updateFrequencyOptions(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'event';
        const freqSelectId = mode === 'create' ? `${prefix}Freq` : 'editEventFreq';
        const freqSelect = document.getElementById(freqSelectId);
        if (!freqSelect) return;
        
        const frequency = freqSelect.value;
        const weekdayContainerId = mode === 'create' ? `${prefix}WeekdaysContainer` : 'editEventWeekdaysContainer';
        const monthlyOptionsId = mode === 'create' ? `${prefix}MonthlyOptions` : 'editEventMonthlyOptions';
        
        const weekdayContainer = document.getElementById(weekdayContainerId);
        const monthlyOptions = document.getElementById(monthlyOptionsId);

        // 隐藏所有特殊选项
        if (weekdayContainer) weekdayContainer.style.display = 'none';
        if (monthlyOptions) monthlyOptions.style.display = 'none';

        // 根据频率显示相应选项
        switch (frequency) {
            case 'WEEKLY':
                if (weekdayContainer) weekdayContainer.style.display = 'block';
                break;
            case 'MONTHLY':
                if (monthlyOptions) monthlyOptions.style.display = 'block';
                // 使用setTimeout确保DOM更新后再调用
                setTimeout(() => {
                    this.updateEventMonthlyOptions(mode);
                }, 10);
                break;
        }
    }

    // 更新结束条件字段
    updateEndConditionFields(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'editEvent';
        const endTypeSelect = document.getElementById(`${prefix}EndType`);
        if (!endTypeSelect) return;
        
        const endType = endTypeSelect.value;
        const countContainer = document.getElementById(`${prefix}CountContainer`);
        const untilContainer = document.getElementById(`${prefix}UntilContainer`);

        // 隐藏所有结束条件字段
        if (countContainer) countContainer.style.display = 'none';
        if (untilContainer) untilContainer.style.display = 'none';

        // 根据选择显示相应字段
        switch (endType) {
            case 'count':
                if (countContainer) {
                    countContainer.style.display = 'block';
                    const countInput = document.getElementById(`${prefix}Count`);
                    if (countInput && !countInput.value) {
                        countInput.value = '10';
                    }
                }
                break;
            case 'until':
                if (untilContainer) {
                    untilContainer.style.display = 'block';
                }
                break;
        }
    }

    // 构建RRule字符串
    buildRRule(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'editEvent';
        const repeatCheckboxId = mode === 'create' ? `${prefix}IsRecurring` : 'eventRepeat';
        const repeatCheckbox = document.getElementById(repeatCheckboxId);
        if (!repeatCheckbox || !repeatCheckbox.checked) {
            return '';
        }

        const freqSelectId = mode === 'create' ? `${prefix}Freq` : 'editEventFreq';
        const intervalInputId = mode === 'create' ? `${prefix}Interval` : 'editEventInterval';
        
        const frequency = document.getElementById(freqSelectId).value;
        const interval = document.getElementById(intervalInputId).value || '1';

        let rrule = `FREQ=${frequency};INTERVAL=${interval}`;

        // 处理结束条件
        const endTypeSelectId = mode === 'create' ? `${prefix}EndType` : 'editEventEndType';
        const endType = document.getElementById(endTypeSelectId).value;
        switch (endType) {
            case 'count':
                const countInputId = mode === 'create' ? `${prefix}Count` : `${prefix}Count`;
                const count = document.getElementById(countInputId).value;
                if (count) {
                    rrule += `;COUNT=${count}`;
                }
                break;
            case 'until':
                const untilInputId = mode === 'create' ? `${prefix}Until` : `${prefix}Until`;
                const until = document.getElementById(untilInputId).value;
                if (until) {
                    // 转换为UTC格式的RRULE日期格式
                    const untilDate = new Date(until + 'T23:59:59');
                    const utcUntil = untilDate.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
                    rrule += `;UNTIL=${utcUntil}`;
                }
                break;
        }

        // 处理周重复的星期几选择
        if (frequency === 'WEEKLY') {
            const weekdayContainerId = mode === 'create' ? `${prefix}WeekdaysContainer` : 'editEventWeekdaysContainer';
            const weekdayContainer = document.getElementById(weekdayContainerId);
            if (weekdayContainer) {
                const activeButtons = weekdayContainer.querySelectorAll('.weekday-btn.active');
                const weekdays = Array.from(activeButtons).map(btn => btn.dataset.day).filter(day => day);
                
                if (weekdays.length > 0) {
                    rrule += `;BYDAY=${weekdays.join(',')}`;
                }
            }
        }

        // 处理月重复类型
        if (frequency === 'MONTHLY') {
            const monthlyTypeSelectId = mode === 'create' ? `${prefix}MonthlyType` : 'editEventMonthlyType';
            const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
            if (monthlyTypeSelect) {
                const monthlyType = monthlyTypeSelect.value;
                
                if (monthlyType === 'bymonthday') {
                    // 按日期重复
                    const monthlyDateSelectId = mode === 'create' ? `${prefix}MonthlyDate` : 'editEventMonthlyDate';
                    const monthlyDateSelect = document.getElementById(monthlyDateSelectId);
                    if (monthlyDateSelect && monthlyDateSelect.value) {
                        const dayOfMonth = monthlyDateSelect.value;
                        rrule += `;BYMONTHDAY=${dayOfMonth}`;
                    }
                } else if (monthlyType === 'byweekday') {
                    // 按星期重复
                    const monthlyWeekSelectId = mode === 'create' ? `${prefix}MonthlyWeek` : 'editEventMonthlyWeek';
                    const monthlyWeekdaySelectId = mode === 'create' ? `${prefix}MonthlyWeekday` : 'editEventMonthlyWeekday';
                    const monthlyWeekSelect = document.getElementById(monthlyWeekSelectId);
                    const monthlyWeekdaySelect = document.getElementById(monthlyWeekdaySelectId);
                    
                    if (monthlyWeekSelect && monthlyWeekdaySelect && 
                        monthlyWeekSelect.value && monthlyWeekdaySelect.value) {
                        const weekNum = monthlyWeekSelect.value;
                        const weekday = monthlyWeekdaySelect.value;
                        rrule += `;BYDAY=${weekNum}${weekday}`;
                    }
                }
                // simple模式（每隔指定月数）是默认行为，不需要特殊处理
            }
        }

        return rrule;
    }

    // 解析RRule到UI
    parseRRuleToUI(rruleString, mode) {
        console.log('=== rrule-manager parseRRuleToUI called ===');
        console.log('rruleString:', rruleString, 'mode:', mode);
        
        const prefix = mode === 'create' ? 'newEvent' : 'editEvent';
        // 修复：编辑模式下的元素ID
        const repeatCheckboxId = mode === 'create' ? `${prefix}IsRecurring` : 'eventRepeat';
        const optionsId = mode === 'create' ? `${prefix}RecurringOptions` : 'editEventRecurringOptions';
        
        const repeatCheckbox = document.getElementById(repeatCheckboxId);
        const options = document.getElementById(optionsId);

        console.log('Looking for elements:');
        console.log('repeatCheckboxId:', repeatCheckboxId, 'element:', repeatCheckbox);
        console.log('optionsId:', optionsId, 'element:', options);

        if (!rruleString || !repeatCheckbox) {
            console.log('No rrule or checkbox, disabling repeat');
            if (repeatCheckbox) repeatCheckbox.checked = false;
            if (options) options.style.display = 'none';
            return;
        }

        // 启用重复选项
        console.log('Enabling repeat options');
        repeatCheckbox.checked = true;
        if (options) options.style.display = 'block';

        // 解析RRule字符串
        const rules = {};
        rruleString.split(';').forEach(part => {
            const [key, value] = part.split('=');
            if (key && value) {
                rules[key] = value;
            }
        });

        console.log('Parsed rules:', rules);

        // 设置频率 - 修复元素ID
        const freqSelectId = mode === 'create' ? `${prefix}Freq` : `${prefix}Freq`;
        const freqSelect = document.getElementById(freqSelectId);
        console.log('freqSelectId:', freqSelectId, 'element:', freqSelect);
        if (freqSelect && rules.FREQ) {
            console.log(`Setting frequency: ${rules.FREQ}`);
            freqSelect.value = rules.FREQ;
            // 触发change事件以更新相关UI
            freqSelect.dispatchEvent(new Event('change'));
        }

        // 设置间隔 - 修复元素ID
        const intervalInputId = mode === 'create' ? `${prefix}Interval` : `${prefix}Interval`;
        const intervalInput = document.getElementById(intervalInputId);
        console.log('intervalInputId:', intervalInputId, 'element:', intervalInput);
        if (intervalInput && rules.INTERVAL) {
            console.log(`Setting interval: ${rules.INTERVAL}`);
            intervalInput.value = rules.INTERVAL;
        }

        // 设置结束条件 - 修复元素ID
        const endTypeSelectId = mode === 'create' ? `${prefix}EndType` : `${prefix}EndType`;
        const endTypeSelect = document.getElementById(endTypeSelectId);
        console.log('endTypeSelectId:', endTypeSelectId, 'element:', endTypeSelect);
        
        if (rules.COUNT) {
            console.log('Setting end type to count with value:', rules.COUNT);
            if (endTypeSelect) {
                endTypeSelect.value = 'count';
                endTypeSelect.dispatchEvent(new Event('change')); // 触发UI更新
            }
            const countInputId = mode === 'create' ? `${prefix}Count` : `${prefix}Count`;
            const countInput = document.getElementById(countInputId);
            if (countInput) {
                countInput.value = rules.COUNT;
                console.log(`Set count to: ${rules.COUNT}`);
            }
        } else if (rules.UNTIL) {
            console.log('Setting end type to until with value:', rules.UNTIL);
            if (endTypeSelect) {
                endTypeSelect.value = 'until';
                endTypeSelect.dispatchEvent(new Event('change')); // 触发UI更新
            }
            const untilInputId = mode === 'create' ? `${prefix}Until` : `${prefix}Until`;
            const untilInput = document.getElementById(untilInputId);
            if (untilInput) {
                // 解析UNTIL日期
                try {
                    let dateStr = rules.UNTIL;
                    // 处理格式：20251023T000000Z -> 2025-10-23
                    if (dateStr.includes('T')) {
                        dateStr = dateStr.split('T')[0];
                    }
                    if (dateStr.length === 8) {
                        dateStr = dateStr.substring(0, 4) + '-' + dateStr.substring(4, 6) + '-' + dateStr.substring(6, 8);
                    }
                    untilInput.value = dateStr;
                    console.log(`Set until date to: ${dateStr}`);
                } catch (error) {
                    console.error('Error parsing until date:', error);
                }
            }
        } else {
            console.log('Setting end type to never');
            if (endTypeSelect) {
                endTypeSelect.value = 'never';
                endTypeSelect.dispatchEvent(new Event('change')); // 触发UI更新
            }
        }

        // 设置星期几选择（周重复）
        if (rules.BYDAY && rules.FREQ === 'WEEKLY') {
            console.log('Setting weekly BYDAY:', rules.BYDAY);
            const weekdays = rules.BYDAY.split(',');
            const weekdayContainerId = mode === 'create' ? `${prefix}WeekdaysContainer` : 'editEventWeekdaysContainer';
            const weekdayContainer = document.getElementById(weekdayContainerId);
            console.log('weekdayContainerId:', weekdayContainerId, 'element:', weekdayContainer);
            if (weekdayContainer) {
                // 确保容器可见
                weekdayContainer.style.display = 'block';
                
                const buttons = weekdayContainer.querySelectorAll('.weekday-btn');
                // 首先重置所有按钮状态
                buttons.forEach(btn => {
                    btn.classList.remove('active', 'btn-primary');
                    btn.classList.add('btn-outline-primary');
                });
                
                // 然后设置选中的星期几
                buttons.forEach(btn => {
                    if (weekdays.includes(btn.dataset.day)) {
                        this.toggleWeekdayButton(btn);
                        console.log(`Toggled weekday button: ${btn.dataset.day}`);
                    }
                });
            } else {
                console.warn('Weekday container not found:', weekdayContainerId);
            }
        }

        // 设置月重复类型
        if (rules.FREQ === 'MONTHLY') {
            console.log('Setting monthly options');
            
            // 确保月重复选项容器可见
            const monthlyOptionsId = mode === 'create' ? `${prefix}MonthlyOptions` : 'editEventMonthlyOptions';
            const monthlyOptionsContainer = document.getElementById(monthlyOptionsId);
            if (monthlyOptionsContainer) {
                monthlyOptionsContainer.style.display = 'block';
                console.log('Made monthly options container visible:', monthlyOptionsId);
            }
            
            if (rules.BYMONTHDAY) {
                // 按日期重复
                const monthlyTypeSelectId = mode === 'create' ? `${prefix}MonthlyType` : 'editEventMonthlyType';
                const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.value = 'bymonthday';
                    console.log('Set monthly type to bymonthday');
                    // 触发change事件以更新相关UI
                    monthlyTypeSelect.dispatchEvent(new Event('change'));
                }
                
                const monthlyDateSelectId = mode === 'create' ? `${prefix}MonthlyDate` : 'editEventMonthlyDate';
                const monthlyDateSelect = document.getElementById(monthlyDateSelectId);
                if (monthlyDateSelect) {
                    monthlyDateSelect.value = rules.BYMONTHDAY;
                    console.log(`Set monthly date to: ${rules.BYMONTHDAY}`);
                }
            } else if (rules.BYDAY) {
                // 按星期重复
                const monthlyTypeSelectId = mode === 'create' ? `${prefix}MonthlyType` : 'editEventMonthlyType';
                const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.value = 'byweekday';
                    console.log('Set monthly type to byweekday');
                    // 触发change事件以更新相关UI
                    monthlyTypeSelect.dispatchEvent(new Event('change'));
                }
                
                // 解析BYDAY（如：3WE表示第三个星期三）
                // 修复：处理不带前缀数字的格式，以及多个BYDAY值中的第一个
                let byDayValue = rules.BYDAY;
                
                // 如果BYDAY包含多个值（用逗号分隔），只取第一个用于月重复显示
                if (byDayValue.includes(',')) {
                    byDayValue = byDayValue.split(',')[0];
                    console.log('Multiple BYDAY values found, using first one for monthly display:', byDayValue);
                }
                
                // 匹配带数字前缀的格式（如3WE）或不带数字的格式（如WE）
                const byDayMatch = byDayValue.match(/^([+-]?\d+)?([A-Z]{2})$/);
                if (byDayMatch) {
                    const weekNum = byDayMatch[1] || '1'; // 如果没有数字前缀，默认为第1个
                    const weekday = byDayMatch[2];
                    
                    console.log(`Parsed BYDAY: weekNum=${weekNum}, weekday=${weekday}`);
                    
                    const monthlyWeekSelectId = mode === 'create' ? `${prefix}MonthlyWeek` : 'editEventMonthlyWeek';
                    const monthlyWeekdaySelectId = mode === 'create' ? `${prefix}MonthlyWeekday` : 'editEventMonthlyWeekday';
                    
                    const monthlyWeekSelect = document.getElementById(monthlyWeekSelectId);
                    const monthlyWeekdaySelect = document.getElementById(monthlyWeekdaySelectId);
                    
                    if (monthlyWeekSelect) {
                        monthlyWeekSelect.value = weekNum;
                        console.log(`Set monthly week to: ${weekNum}`);
                    }
                    if (monthlyWeekdaySelect) {
                        monthlyWeekdaySelect.value = weekday;
                        console.log(`Set monthly weekday to: ${weekday}`);
                    }
                } else {
                    console.warn('Could not parse BYDAY value for monthly repeat:', byDayValue);
                }
            } else {
                // 简单月重复
                const monthlyTypeSelectId = mode === 'create' ? `${prefix}MonthlyType` : 'editEventMonthlyType';
                const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
                if (monthlyTypeSelect) {
                    monthlyTypeSelect.value = 'simple';
                    console.log('Set monthly type to simple');
                    // 触发change事件以更新相关UI
                    monthlyTypeSelect.dispatchEvent(new Event('change'));
                }
            }
            
            // 触发月重复选项更新
            this.updateEventMonthlyOptions(mode);
        }

        // 更新UI显示
        this.updateFrequencyOptions(mode);
        this.updateEndConditionFields(mode);
        this.updateRulePreview(mode);
    }

    // 更新规则预览
    updateRulePreview(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'event';
        const previewElement = document.getElementById(`${prefix}RulePreview`);
        if (!previewElement) return;

        const rrule = this.buildRRule(mode);
        if (!rrule) {
            previewElement.textContent = '无重复';
            return;
        }

        // 生成人类可读的描述
        const description = this.generateRuleDescription(rrule, mode);
        previewElement.textContent = description;
    }

    // 生成规则描述
    generateRuleDescription(rrule, mode) {
        const rules = {};
        rrule.split(';').forEach(part => {
            const [key, value] = part.split('=');
            if (key && value) {
                rules[key] = value;
            }
        });

        const frequency = rules.FREQ;
        const interval = parseInt(rules.INTERVAL) || 1;

        let description = '';

        // 基本频率描述
        switch (frequency) {
            case 'DAILY':
                description = interval === 1 ? '每天' : `每${interval}天`;
                break;
            case 'WEEKLY':
                description = interval === 1 ? '每周' : `每${interval}周`;
                break;
            case 'MONTHLY':
                description = interval === 1 ? '每月' : `每${interval}个月`;
                break;
            case 'YEARLY':
                description = interval === 1 ? '每年' : `每${interval}年`;
                break;
        }

        // 星期几描述（周重复）
        if (rules.BYDAY && frequency === 'WEEKLY') {
            const weekdays = rules.BYDAY.split(',');
            const dayNames = {
                'MO': '周一', 'TU': '周二', 'WE': '周三', 'TH': '周四',
                'FR': '周五', 'SA': '周六', 'SU': '周日'
            };
            const dayDescriptions = weekdays.map(day => dayNames[day]).filter(Boolean);
            if (dayDescriptions.length > 0) {
                description += ` (${dayDescriptions.join('、')})`;
            }
        }

        // 月重复类型描述
        if (frequency === 'MONTHLY' && rules.BYDAY) {
            description += ' (按星期几)';
        }

        // 结束条件描述
        if (rules.COUNT) {
            description += `，共${rules.COUNT}次`;
        } else if (rules.UNTIL) {
            const untilDate = new Date(rules.UNTIL.replace(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z/, '$1-$2-$3T$4:$5:$6Z'));
            description += `，直到${untilDate.toLocaleDateString()}`;
        }

        return description;
    }

    // 验证RRule设置
    validateRRuleSettings(mode) {
        const prefix = mode === 'create' ? 'newEvent' : 'event';
        const repeatCheckbox = document.getElementById(`${prefix}IsRecurring`);
        if (!repeatCheckbox || !repeatCheckbox.checked) {
            return true; // 不重复时总是有效
        }

        // 检查结束条件
        const endType = document.getElementById(`${prefix}EndType`).value;
        switch (endType) {
            case 'count':
                const count = document.getElementById(`${prefix}Count`).value;
                if (!count || parseInt(count) < 1) {
                    alert('请输入有效的重复次数（至少1次）');
                    return false;
                }
                break;
            case 'until':
                const until = document.getElementById(`${prefix}Until`).value;
                if (!until) {
                    alert('请选择重复结束日期');
                    return false;
                }
                // 检查结束日期是否在开始日期之后
                const startInput = document.getElementById(mode === 'create' ? 'newEventStart' : 'eventStart');
                if (startInput && startInput.value) {
                    const startDate = new Date(startInput.value);
                    const untilDate = new Date(until);
                    if (untilDate <= startDate) {
                        alert('重复结束日期必须在开始日期之后');
                        return false;
                    }
                }
                break;
        }

        // 检查周重复的星期几选择
        const frequency = document.getElementById(`${prefix}Freq`).value;
        if (frequency === 'WEEKLY') {
            const weekdayContainer = document.getElementById(`${prefix}WeekdaysContainer`);
            if (weekdayContainer) {
                const selectedDays = weekdayContainer.querySelectorAll('.weekday-btn.active');
                if (selectedDays.length === 0) {
                    alert('周重复时请至少选择一个星期几');
                    return false;
                }
            }
        }

        return true;
    }

    // 更新事件月重复选项
    updateEventMonthlyOptions(mode) {
        // 将'new'映射为'create'
        const actualMode = mode === 'new' ? 'create' : mode;
        const prefix = actualMode === 'create' ? 'newEvent' : 'event';
        
        let monthlyType;
        
        if (actualMode === 'create') {
            // 新建模式：使用select元素
            const monthlyTypeSelectId = `${prefix}MonthlyType`;
            const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
            
            if (!monthlyTypeSelect) {
                console.warn(`MonthlyType select not found for ID: ${monthlyTypeSelectId}`);
                return;
            }
            monthlyType = monthlyTypeSelect.value;
        } else {
            // 编辑模式：现在也使用select dropdown
            const monthlyTypeSelectId = 'editEventMonthlyType';
            const monthlyTypeSelect = document.getElementById(monthlyTypeSelectId);
            if (!monthlyTypeSelect) {
                console.warn(`MonthlyType select not found for ID: ${monthlyTypeSelectId}`);
                return;
            }
            monthlyType = monthlyTypeSelect.value;
        }
        
        console.log('Monthly type:', monthlyType);
        
        // 获取各种选项元素
        const monthlyDateOptionsId = actualMode === 'create' ? `${prefix}MonthlyDateOptions` : 'editEventMonthlyDateOptions';
        const monthlyWeekOptionsId = actualMode === 'create' ? `${prefix}MonthlyWeekOptions` : 'editEventMonthlyWeekOptions';
        const monthlyWeekdayOptionsId = actualMode === 'create' ? `${prefix}MonthlyWeekdayOptions` : 'editEventMonthlyWeekdayOptions';
        
        const monthlyDateOptions = document.getElementById(monthlyDateOptionsId);
        const monthlyWeekOptions = document.getElementById(monthlyWeekOptionsId);
        const monthlyWeekdayOptions = document.getElementById(monthlyWeekdayOptionsId);
        
        // 首先隐藏所有选项
        if (monthlyDateOptions) monthlyDateOptions.style.display = 'none';
        if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'none';
        if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'none';
        
        // 根据类型显示对应选项
        if (monthlyType === 'bymonthday') {
            // 按日期重复 - 显示日期选择器
            if (monthlyDateOptions) monthlyDateOptions.style.display = 'block';
        } else if (monthlyType === 'byweekday') {
            // 按星期重复 - 显示星期选择器
            if (monthlyWeekOptions) monthlyWeekOptions.style.display = 'block';
            if (monthlyWeekdayOptions) monthlyWeekdayOptions.style.display = 'block';
        }
        
        // 更新预览
        this.updateRulePreview(actualMode);
    }
}

// 全局函数，供HTML中使用 - Events专用
function toggleEventRepeatOptions(mode) {
    if (window.rruleManager) {
        window.rruleManager.toggleRepeatOptions(mode);
    }
}

function updateEventFrequencyOptions(mode) {
    if (window.rruleManager) {
        window.rruleManager.updateFrequencyOptions(mode);
    }
}

function buildEventRruleFromUI(mode) {
    if (window.rruleManager) {
        return window.rruleManager.buildRRule(mode);
    }
    return '';
}

function parseRruleToUI(rruleString, mode) {
    if (window.rruleManager) {
        window.rruleManager.parseRRuleToUI(rruleString, mode);
    }
}

function validateRruleSettings(mode) {
    if (window.rruleManager) {
        return window.rruleManager.validateRRuleSettings(mode);
    }
    return true;
}
// 导出实例
// rruleManager实例将在HTML中创建
