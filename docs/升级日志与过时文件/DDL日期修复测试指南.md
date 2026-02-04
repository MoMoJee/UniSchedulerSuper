# DDL日期修复测试指南

## 测试前准备

1. **重启Django服务器**
   ```powershell
   # 在终端中按 Ctrl+C 停止服务器
   # 然后重新启动
   python manage.py runserver
   ```

2. **清除浏览器缓存**（如果需要）
   - 按 F12 打开开发者工具
   - 右键点击刷新按钮 → 选择"清空缓存并硬性重新加载"

---

## 测试场景1：创建每日重复日程

### 步骤
1. 点击日历创建新日程
2. 填写信息：
   - 标题：DDL测试-每日
   - 开始：2025-10-14 18:00
   - 结束：2025-10-14 19:00
   - ✅ 勾选"重复日程"
   - 重复规则：每天，无限重复
   - DDL：19:00（注意：应该只显示时间选择器）
3. 保存日程

### 验证数据库
打开浏览器控制台（F12），执行：
```javascript
// 获取events数据
fetch('/core/get_events/')
  .then(r => r.json())
  .then(data => {
    // 筛选同一系列的日程
    const testEvents = data.filter(e => e.title === 'DDL测试-每日');
    
    // 按开始时间排序
    testEvents.sort((a, b) => a.start.localeCompare(b.start));
    
    // 检查前5个日程
    testEvents.slice(0, 5).forEach(e => {
      console.log(`日期: ${e.start.split('T')[0]}`);
      console.log(`  Start: ${e.start}`);
      console.log(`  End:   ${e.end}`);
      console.log(`  DDL:   ${e.ddl}`);
      console.log(`  匹配:  ${e.end === e.ddl ? '✅' : '❌'}`);
      console.log('---');
    });
  });
```

### 预期结果
```
日期: 2025-10-14
  Start: 2025-10-14T18:00:00
  End:   2025-10-14T19:00:00
  DDL:   2025-10-14T19:00:00
  匹配:  ✅
---
日期: 2025-10-15
  Start: 2025-10-15T18:00:00
  End:   2025-10-15T19:00:00
  DDL:   2025-10-15T19:00:00  ← 日期正确变化
  匹配:  ✅
---
日期: 2025-10-16
  Start: 2025-10-16T18:00:00
  End:   2025-10-16T19:00:00
  DDL:   2025-10-16T19:00:00  ← 日期正确变化
  匹配:  ✅
---
```

**❌ 如果看到所有DDL都是 `2025-10-14T19:00:00`，说明修复未生效**

---

## 测试场景2：创建每周重复日程

### 步骤
1. 创建新日程
2. 填写信息：
   - 标题：DDL测试-每周
   - 开始：2025-10-14 10:00
   - 结束：2025-10-14 11:00
   - ✅ 勾选"重复日程"
   - 重复规则：每周，每周一
   - DDL：11:00
3. 保存日程

### 验证
```javascript
fetch('/core/get_events/')
  .then(r => r.json())
  .then(data => {
    const testEvents = data.filter(e => e.title === 'DDL测试-每周');
    testEvents.sort((a, b) => a.start.localeCompare(b.start));
    
    testEvents.slice(0, 4).forEach(e => {
      console.log(`${e.start.split('T')[0]} (${new Date(e.start).toLocaleDateString('zh-CN', {weekday: 'long'})})`);
      console.log(`  DDL: ${e.ddl}`);
      console.log(`  匹配: ${e.end === e.ddl ? '✅' : '❌'}`);
    });
  });
```

### 预期结果
```
2025-10-14 (星期二)  ← 主事件
  DDL: 2025-10-14T11:00:00
  匹配: ✅
2025-10-21 (星期二)
  DDL: 2025-10-21T11:00:00  ← 日期+7天
  匹配: ✅
2025-10-28 (星期二)
  DDL: 2025-10-28T11:00:00  ← 日期+14天
  匹配: ✅
```

---

## 测试场景3：创建每月重复日程

### 步骤
1. 创建新日程
2. 填写信息：
   - 标题：DDL测试-每月
   - 开始：2025-10-14 14:00
   - 结束：2025-10-14 15:00
   - ✅ 勾选"重复日程"
   - 重复规则：每月，每月第2个周一
   - DDL：15:00
3. 保存日程

### 验证
```javascript
fetch('/core/get_events/')
  .then(r => r.json())
  .then(data => {
    const testEvents = data.filter(e => e.title === 'DDL测试-每月');
    testEvents.sort((a, b) => a.start.localeCompare(b.start));
    
    testEvents.slice(0, 3).forEach(e => {
      const date = new Date(e.start);
      console.log(`${e.start.split('T')[0]} (${date.getFullYear()}年${date.getMonth()+1}月)`);
      console.log(`  DDL: ${e.ddl}`);
      console.log(`  匹配: ${e.end === e.ddl ? '✅' : '❌'}`);
    });
  });
```

### 预期结果
```
2025-10-14 (2025年10月)
  DDL: 2025-10-14T15:00:00
  匹配: ✅
2025-11-10 (2025年11月)  ← 11月的第2个周一
  DDL: 2025-11-10T15:00:00  ← 日期变为11月
  匹配: ✅
2025-12-08 (2025年12月)  ← 12月的第2个周一
  DDL: 2025-12-08T15:00:00  ← 日期变为12月
  匹配: ✅
```

---

## 测试场景4：编辑现有重复日程

如果你之前创建了重复日程，需要**重新保存**才能应用修复：

### 步骤
1. 找到之前创建的"测试重复"日程（第一个实例）
2. 点击编辑
3. 不做任何修改，直接点击"保存整个系列"
4. 刷新页面

### 验证
检查数据库中该系列的所有日程，ddl日期应该现在正确了。

---

## 快速检查脚本

在浏览器控制台中运行此脚本，一次性检查所有重复日程的ddl：

```javascript
fetch('/core/get_events/')
  .then(r => r.json())
  .then(data => {
    // 只检查重复日程
    const recurringEvents = data.filter(e => e.is_recurring && e.ddl);
    
    // 按系列分组
    const seriesMap = {};
    recurringEvents.forEach(e => {
      const sid = e.series_id;
      if (!seriesMap[sid]) seriesMap[sid] = [];
      seriesMap[sid].push(e);
    });
    
    // 检查每个系列
    Object.entries(seriesMap).forEach(([sid, events]) => {
      events.sort((a, b) => a.start.localeCompare(b.start));
      
      console.log(`\n系列: ${events[0].title} (${events.length}个日程)`);
      
      let allCorrect = true;
      events.forEach((e, i) => {
        const endDate = e.end.split('T')[0];
        const ddlDate = e.ddl.split('T')[0];
        const endTime = e.end.split('T')[1];
        const ddlTime = e.ddl.split('T')[1];
        
        const dateMatch = endDate === ddlDate;
        const timeMatch = endTime === ddlTime;
        
        if (!dateMatch || !timeMatch) {
          allCorrect = false;
          console.log(`  ❌ #${i+1}: ${e.start}`);
          console.log(`     End: ${e.end}`);
          console.log(`     DDL: ${e.ddl}`);
          console.log(`     问题: ${!dateMatch ? '日期不匹配' : '时间不匹配'}`);
        }
      });
      
      if (allCorrect) {
        console.log(`  ✅ 所有${events.length}个日程的DDL都正确`);
      }
    });
    
    console.log('\n检查完成！');
  });
```

---

## 常见问题

### Q1: 修复后，旧的日程怎么办？
**A:** 旧日程不会自动更新。有两个选择：
1. **重新保存**：编辑旧日程 → 点击"保存整个系列"
2. **删除重建**：删除旧日程，重新创建

### Q2: 如何确认修复已生效？
**A:** 看代码修改时间：
```powershell
(Get-Item "d:\PROJECTS\UniSchedulerSuper\core\views_events.py").LastWriteTime
```
应该显示今天的时间（2025-10-14）

### Q3: 浏览器显示的日程正确，但数据库不对？
**A:** 可能是缓存问题：
1. 清除浏览器缓存
2. 重启Django服务器
3. 硬刷新页面（Ctrl+Shift+R）

### Q4: 测试脚本报错"CORS"？
**A:** 确保在**同一个页面**运行脚本（例如在日历页面打开控制台），不要在独立的控制台标签页运行。

---

## 检查清单

测试完成后，确认以下几点：

- [ ] 每日重复：每个日程的ddl日期 = 该日程的日期
- [ ] 每周重复：每个日程的ddl日期 = 该日程的日期
- [ ] 每月重复：每个日程的ddl日期 = 该日程的日期
- [ ] 所有日程的ddl时间 = 创建时设定的统一时间点
- [ ] 编辑重复日程后，新生成的实例也有正确的ddl
- [ ] UI上ddl控件在重复日程模式下只显示时间选择器

**全部通过 = 修复成功！✅**
