// 全局配置对象
let config = {};
let tagConfig = {};

// 显示提示信息
function showAlert(message, type = 'success') {
    const alertBox = document.getElementById('alertBox');
    if (!alertBox) {
        console.error('Alert box element not found');
        return;
    }
    alertBox.className = `alert alert-${type}`;
    alertBox.textContent = message;  // 使用 textContent 替代 innerHTML
    alertBox.style.display = 'block';
    
    setTimeout(() => {
        if (alertBox) {
            alertBox.style.display = 'none';
        }
    }, 3000);
}

// 加载配置
async function loadConfig() {
    try {
        const [configResponse, tagConfigResponse] = await Promise.all([
            axios.get('/api/config'),
            axios.get('/api/tag-config')
        ]);
        
        config = configResponse.data;
        tagConfig = tagConfigResponse.data;
        
        updateUI();
        showAlert('配置已加载');
    } catch (error) {
        showAlert('加载配置失败：' + error.message, 'danger');
    }
}

// 保存配置
async function saveConfig() {
    try {
        // 收集表单数据
        const mainConfig = {
            nick_name_white_list: document.getElementById('whiteList').value.split('\n').filter(x => x),
            nick_name_black_list: document.getElementById('blackList').value.split('\n').filter(x => x),
            random_reply_delay_min: parseInt(document.getElementById('minDelay').value),
            random_reply_delay_max: parseInt(document.getElementById('maxDelay').value),
            updateAutoReplyTable: true,
            channel_type: "wx",
            model: config.model || "coze",  // 使用原有的 model 值，如果没有则默认为 coze
            debug: false
        };

        const tagConfigData = {
            enable: document.getElementById('enableTag').checked,
            tag_prefix: document.getElementById('tagPrefix').value,
            allow_all_add_tag: document.getElementById('allowAddTag').checked,
            allow_all_remove_tag: document.getElementById('allowRemoveTag').checked,
            allow_all_view_tag: document.getElementById('allowViewTag').checked,
            allow_all_list_tag: document.getElementById('allowListTag').checked,
            admin_users: document.getElementById('adminUsers').value.split('\n').filter(x => x),
            enabled_tags: document.getElementById('enabledTags').value.split('\n').filter(x => x),
            auto_reply: getAutoReplyConfig(),
            tags_friends: getTagFriendsConfig(),
            scheduled_tasks: getScheduledTasksConfig()
        };

        // 添加no_backup参数，告诉后端不要生成备份
        await Promise.all([
            axios.post('/api/config', mainConfig, { params: { no_backup: true } }),
            axios.post('/api/tag-config', tagConfigData, { params: { no_backup: true } })
        ]);

        showAlert('配置已保存');
        
        // 更新全局配置对象
        config = mainConfig;
        tagConfig = tagConfigData;
        
    } catch (error) {
        showAlert('保存配置失败：' + error.message, 'danger');
        console.error('保存配置错误：', error);
    }
}

// 更新UI显示
function updateUI() {
    try {
        // 更新名单配置
        const whiteList = document.getElementById('whiteList');
        const blackList = document.getElementById('blackList');
        if (whiteList) whiteList.value = (config.nick_name_white_list || []).join('\n');
        if (blackList) blackList.value = (config.nick_name_black_list || []).join('\n');
        
        // 更新延时配置
        const minDelay = document.getElementById('minDelay');
        const maxDelay = document.getElementById('maxDelay');
        if (minDelay) minDelay.value = config.random_reply_delay_min || 2;
        if (maxDelay) maxDelay.value = config.random_reply_delay_max || 4;
        
        // 更新标签配置
        const elements = {
            enableTag: document.getElementById('enableTag'),
            tagPrefix: document.getElementById('tagPrefix'),
            allowAddTag: document.getElementById('allowAddTag'),
            allowRemoveTag: document.getElementById('allowRemoveTag'),
            allowViewTag: document.getElementById('allowViewTag'),
            allowListTag: document.getElementById('allowListTag'),
            adminUsers: document.getElementById('adminUsers'),
            enabledTags: document.getElementById('enabledTags')
        };

        // 安全地设置元素值
        if (elements.enableTag) elements.enableTag.checked = tagConfig.enable || false;
        if (elements.tagPrefix) elements.tagPrefix.value = tagConfig.tag_prefix || '$';
        if (elements.allowAddTag) elements.allowAddTag.checked = tagConfig.allow_all_add_tag || false;
        if (elements.allowRemoveTag) elements.allowRemoveTag.checked = tagConfig.allow_all_remove_tag || false;
        if (elements.allowViewTag) elements.allowViewTag.checked = tagConfig.allow_all_view_tag || false;
        if (elements.allowListTag) elements.allowListTag.checked = tagConfig.allow_all_list_tag || false;
        if (elements.adminUsers) elements.adminUsers.value = (tagConfig.admin_users || []).join('\n');
        if (elements.enabledTags) elements.enabledTags.value = (tagConfig.enabled_tags || []).join('\n');
        
        // 更新表格
        updateAutoReplyTable();
        updateTagFriendsTable();
        updateScheduledTasksTable();
        updateTagSelects();
    } catch (error) {
        console.error('Error updating UI:', error);
        showAlert('更新界面时出错：' + error.message, 'danger');
    }
}

// 获取自动回复配置
function getAutoReplyConfig() {
    const config = {};
    const rows = document.querySelectorAll('#autoReplyTable tbody tr');
    rows.forEach(row => {
        const tag = row.querySelector('.tag-name').value;
        const reply = row.querySelector('.reply-content').value;
        if (tag && reply) {
            config[tag] = reply;
        }
    });
    return config;
}

// 获取标签好友配置
function getTagFriendsConfig() {
    const config = {};
    const rows = document.querySelectorAll('#tagFriendsTable tbody tr');
    rows.forEach(row => {
        const tag = row.querySelector('.tag-select').value;
        const friends = row.querySelector('.friends-input').value.split(',').map(f => f.trim()).filter(f => f);
        if (tag && friends.length) {
            config[tag] = friends;
        }
    });
    return config;
}

// 获取定时任务配置
function getScheduledTasksConfig() {
    const tasks = [];
    const rows = document.querySelectorAll('#scheduledTasksTable tbody tr');
    rows.forEach(row => {
        const task = {
            id: row.querySelector('.task-id').textContent,
            tag: row.querySelector('.task-tag').value,
            time: row.querySelector('.task-time').value,
            message: row.querySelector('.task-message').value
        };
        if (task.tag && task.time && task.message) {
            tasks.push(task);
        }
    });
    return tasks;
}

// 添加自动回复行
function addAutoReplyRow(tag = '', reply = '') {
    const tbody = document.querySelector('#autoReplyTable tbody');
    if (!tbody) {
        console.error('Auto reply table not found');
        return;
    }
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="text" class="form-control tag-name" value="${tag}"></td>
        <td><input type="text" class="form-control reply-content" value="${reply}"></td>
        <td>
            <button class="btn btn-danger btn-sm" onclick="this.closest('tr').remove()">删除</button>
        </td>
    `;
    tbody.appendChild(tr);
}

// 添加标签好友
async function addTagFriends() {
    const tag = document.getElementById('newTagSelect').value;
    const friends = document.getElementById('newFriends').value;
    
    if (!tag || !friends) {
        showAlert('请填写完整的标签和好友信息', 'warning');
        return;
    }
    
    // 确保 tags_friends 存在
    if (!tagConfig.tags_friends) {
        tagConfig.tags_friends = {};
    }
    
    // 获取新好友列表
    const newFriends = friends.split(',').map(f => f.trim()).filter(f => f);
    
    // 如果标签已存在，合并好友列表
    if (tagConfig.tags_friends[tag]) {
        const existingFriends = tagConfig.tags_friends[tag];
        const mergedFriends = [...new Set([...existingFriends, ...newFriends])]; // 使用 Set 去重
        tagConfig.tags_friends[tag] = mergedFriends;
    } else {
        tagConfig.tags_friends[tag] = newFriends;
    }
    
    try {
        // 保存到服务器
        await axios.post('/api/tag-config', tagConfig);
        showAlert('保存成功');
        
        // 更新表格显示
        updateTagFriendsTable();
        
        // 清空输入
        document.getElementById('newFriends').value = '';
    } catch (error) {
        showAlert('保存失败：' + error.message, 'danger');
        console.error('保存标签好友配置错误：', error);
    }
}

// 添加定时任务
async function addScheduledTask() {
    const tag = document.getElementById('newTaskTag').value;
    const scheduleType = document.getElementById('newTaskScheduleType').value;
    const time = document.getElementById('newTaskTime').value;
    const message = document.getElementById('newTaskMessage').value;
    
    if (!tag || !scheduleType || !time || !message) {
        showAlert('请填写完整的任务信息', 'warning');
        return;
    }

    try {
        // 调用后端API添加任务
        const response = await axios.post('/api/tasks', {
            tag: tag,
            schedule_type: scheduleType,
            time: time,
            message: message
        });

        if (response.status === 201) {
            showAlert('任务添加成功', 'success');
            
            // 清空输入
            document.getElementById('newTaskTag').value = '';
            document.getElementById('newTaskScheduleType').value = 'today';
            document.getElementById('newTaskTime').value = '';
            document.getElementById('newTaskMessage').value = '';
            
            // 立即刷新任务列表
            await updateScheduledTasksTable();
            
            // 立即检查任务状态
            checkTaskStatus();
        }
    } catch (error) {
        console.error('添加任务失败:', error);
        showAlert(error.response?.data?.error || '添加任务失败', 'danger');
    }
}

// 发送群发消息
async function sendBroadcast() {
    const tag = document.getElementById('broadcastTag').value;
    const message = document.getElementById('broadcastMessage').value;
    
    if (!tag || !message) {
        showAlert('请选择标签并输入消息内容', 'warning');
        return;
    }
    
    try {
        const response = await axios.post('/api/broadcast', { tag, message });
        const result = response.data;
        
        // 显示发送结果
        const successCount = result.success_count || 0;
        const failCount = result.fail_count || 0;
        const failedFriends = result.failed_friends || [];
        
        let alertMessage = `消息发送完成\n成功: ${successCount} 条\n失败: ${failCount} 条`;
        if (failCount > 0) {
            alertMessage += '\n\n失败的好友:\n';
            failedFriends.forEach(friend => {
                alertMessage += `${friend.name}: ${friend.error}\n`;
            });
            showAlert(alertMessage, 'warning');
        } else {
            showAlert(alertMessage, 'success');
        }
        
        document.getElementById('broadcastMessage').value = '';
    } catch (error) {
        let errorMessage = '发送消息失败';
        if (error.response && error.response.data && error.response.data.error) {
            errorMessage += ': ' + error.response.data.error;
        } else {
            errorMessage += ': ' + error.message;
        }
        showAlert(errorMessage, 'danger');
    }
}

// 导出配置
async function exportConfig() {
    try {
        const response = await axios.get('/api/export-config', { responseType: 'blob' });
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', `config_backup_${new Date().toISOString().slice(0,10)}.json`);
        document.body.appendChild(link);
        link.click();
        link.remove();
    } catch (error) {
        showAlert('导出配置失败：' + error.message, 'danger');
    }
}

// 导入配置
async function importConfig() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = async (e) => {
            try {
                const config = JSON.parse(e.target.result);
                await axios.post('/api/import-config', config);
                await loadConfig();
                showAlert('配置导入成功');
            } catch (error) {
                showAlert('导入配置失败：' + error.message, 'danger');
            }
        };
        reader.readAsText(file);
    };
    
    input.click();
}

// 更新标签选择下拉列表
function updateTagSelects() {
    // 获取所有标签选择下拉框
    const tagSelects = document.querySelectorAll('.tag-select, #newTaskTag');
    
    // 获取启用的标签列表
    const enabledTags = document.getElementById('enabledTags')?.value.split('\n').filter(x => x) || [];
    
    // 为每个下拉框更新选项
    tagSelects.forEach(select => {
        const currentValue = select.value;
        select.innerHTML = getTagOptionsHtml(currentValue);
        
        // 如果当前值在新的选项中不存在，选择第一个选项
        if (!enabledTags.includes(currentValue) && enabledTags.length > 0) {
            select.value = enabledTags[0];
        }
    });
}

// 获取标签选项HTML
function getTagOptionsHtml(selectedTag = '') {
    const tags = document.getElementById('enabledTags')?.value.split('\n').filter(x => x) || [];
    return tags.map(tag => 
        `<option value="${tag}" ${tag === selectedTag ? 'selected' : ''}>${tag}</option>`
    ).join('');
}

// 获取调度类型选项HTML
function getScheduleTypeOptionsHtml(selectedType = '') {
    const scheduleTypes = [
        { value: 'today', label: '今天' },
        { value: 'tomorrow', label: '明天' },
        { value: 'day_after_tomorrow', label: '后天' },
        { value: 'daily', label: '每天' },
        { value: 'workdays', label: '工作日' },
        { value: 'weekly', label: '每周' },
        { value: 'specific_date', label: '具体日期' },
        { value: 'cron', label: 'Cron表达式' }
    ];
    
    return scheduleTypes.map(type => 
        `<option value="${type.value}" ${type.value === selectedType ? 'selected' : ''}>${type.label}</option>`
    ).join('');
}

// 加载示例配置（仅更新界面，不保存）
function loadExampleConfig() {
    if (confirm('确定要加载示例配置吗？\n\n注意：\n- 这将替换当前界面的所有配置\n- 需要点击保存按钮才会生效\n- 建议先导出当前配置备份')) {
        try {
            // 创建示例配置
            const exampleConfig = {
                main_config: {
                    nick_name_white_list: ['张三', '李四', '王五'],
                    nick_name_black_list: ['广告机器人'],
                    random_reply_delay_min: 2,
                    random_reply_delay_max: 4,
                    updateAutoReplyTable: true,
                    channel_type: "wx",
                    model: "chatgpt",
                    debug: true
                },
                tag_config: {
                    enable: true,
                    tag_prefix: "$",
                    allow_all_add_tag: false,
                    allow_all_remove_tag: false,
                    allow_all_view_tag: true,
                    allow_all_list_tag: true,
                    admin_users: ['管理员1', '管理员2'],
                    enabled_tags: ['朋友', '家人', '同事'],
                    auto_reply: {
                        '朋友': '你好，我现在有事不在，稍后回复你。',
                        '家人': '我在忙，等会儿联系。',
                        '同事': '我在开会，稍后回复。'
                    },
                    tags_friends: {
                        '朋友': ['张三', '李四'],
                        '家人': ['妈妈', '爸爸'],
                        '同事': ['小王', '小李']
                    },
                    scheduled_tasks: [
                        {
                            id: '1',
                            tag: '朋友',
                            time: '09:00',
                            message: '早上好！'
                        },
                        {
                            id: '2',
                            tag: '家人',
                            time: '12:00',
                            message: '午饭时间到了！'
                        }
                    ]
                }
            };

            // 仅更新内存中的配置对象
            config = exampleConfig.main_config;
            tagConfig = exampleConfig.tag_config;
            
            // 更新UI显示
            updateUI();
            
            showAlert('示例配置已加载，请检查配置并点击保存按钮使其生效', 'warning');
        } catch (error) {
            showAlert('加载示例配置失败：' + error.message, 'danger');
            console.error('加载示例配置错误：', error);
        }
    }
}

// 重置配置（仅更新界面，不保存）
function resetConfig() {
    if (confirm('确定要重置所有配置吗？\n\n注意：\n- 这将清空所有现有配置\n- 恢复为默认设置\n- 需要点击保存按钮才会生效\n- 建议先导出当前配置备份')) {
        try {
            // 使用默认配置
            const defaultConfig = getDefaultConfig();
            
            // 更新内存中的配置对象
            config = defaultConfig.main_config;
            tagConfig = defaultConfig.tag_config;
            
            // 更新UI显示
            updateUI();
            
            showAlert('配置已重置为默认值，请检查配置并点击保存按钮使其生效', 'warning');
        } catch (error) {
            showAlert('重置配置失败：' + error.message, 'danger');
            console.error('重置配置错误：', error);
        }
    }
}

// 修改默认配置函数，添加更多默认值
function getDefaultConfig() {
    return {
        main_config: {
            nick_name_white_list: [],
            nick_name_black_list: [],
            random_reply_delay_min: 2,
            random_reply_delay_max: 4,
            updateAutoReplyTable: true,
            channel_type: "wx",
            model: "chatgpt",
            debug: false
        },
        tag_config: {
            enable: false,
            tag_prefix: "$",
            allow_all_add_tag: false,
            allow_all_remove_tag: false,
            allow_all_view_tag: true,
            allow_all_list_tag: true,
            admin_users: [],
            enabled_tags: [],
            auto_reply: {},
            tags_friends: {},
            scheduled_tasks: []
        }
    };
}

// 更新自动回复表格
function updateAutoReplyTable() {
    const tbody = document.querySelector('#autoReplyTable tbody');
    if (!tbody) {
        console.error('Auto reply table not found');
        return;
    }
    
    try {
        tbody.textContent = '';  // 使用 textContent 清空内容
        const autoReply = tagConfig.auto_reply || {};
        Object.entries(autoReply).forEach(([tag, reply]) => {
            addAutoReplyRow(tag, reply);
        });
    } catch (error) {
        console.error('Error updating auto reply table:', error);
    }
}

// 更新标签好友表格
function updateTagFriendsTable() {
    const tbody = document.querySelector('#tagFriendsTable tbody');
    if (!tbody) {
        console.error('Tag friends table not found');
        return;
    }
    
    try {
        tbody.textContent = '';  // 使用 textContent 清空内容
        const tagsFriends = tagConfig.tags_friends || {};
        Object.entries(tagsFriends).forEach(([tag, friends]) => {
            if (!Array.isArray(friends)) return;
            const uniqueFriends = [...new Set(friends)].sort();
            const tr = document.createElement('tr');
            const td1 = document.createElement('td');
            const td2 = document.createElement('td');
            const td3 = document.createElement('td');
            
            const select = document.createElement('select');
            select.className = 'form-select tag-select';
            select.innerHTML = getTagOptionsHtml(tag);
            td1.appendChild(select);
            
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control friends-input';
            input.value = uniqueFriends.join(',');
            td2.appendChild(input);
            
            td3.innerHTML = `
                <button class="btn btn-success btn-sm me-1" onclick="saveTagFriendsRow(this)">保存</button>
                <button class="btn btn-danger btn-sm" onclick="deleteTagFriendsRow(this)">删除</button>
            `;
            
            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tbody.appendChild(tr);
        });
    } catch (error) {
        console.error('Error updating tag friends table:', error);
    }
}

// 更新定时任务表格
async function updateScheduledTasksTable() {
    try {
        const response = await axios.get('/api/tasks');
        const tasks = response.data;
        
        const tbody = document.querySelector('#scheduledTasksTable tbody');
        if (!tbody) {
            console.error('Scheduled tasks table not found');
            return;
        }
        
        // 清空现有内容
        tbody.innerHTML = '';
        
        // 添加所有任务
        tasks.forEach(task => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="task-id">${task.id}</td>
                <td><select class="form-control task-tag">
                    ${getTagOptionsHtml(task.tag)}
                </select></td>
                <td><select class="form-control task-schedule-type">
                    ${getScheduleTypeOptionsHtml(task.schedule_type)}
                </select></td>
                <td><input type="time" class="form-control task-time" value="${task.time}"></td>
                <td><input type="text" class="form-control task-message" value="${task.message}"></td>
                <td class="task-status">
                    ${task.last_execution ? `上次执行: ${task.last_execution}` : '未执行'}
                </td>
                <td>
                    <button class="btn btn-success btn-sm me-1" onclick="saveScheduledTaskRow(this)">保存</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteScheduledTask(this)">删除</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (error) {
        console.error('Error updating scheduled tasks table:', error);
    }
}

// 保存标签好友行
async function saveTagFriendsRow(button) {
    const row = button.closest('tr');
    const tag = row.querySelector('.tag-select').value;
    const friends = row.querySelector('.friends-input').value;
    
    if (!tag || !friends) {
        showAlert('请填写完整的标签和好友信息', 'warning');
        return;
    }
    
    // 更新配置
    if (!tagConfig.tags_friends) {
        tagConfig.tags_friends = {};
    }
    tagConfig.tags_friends[tag] = friends.split(',').map(f => f.trim()).filter(f => f);
    
    try {
        // 保存到服务器
        await axios.post('/api/tag-config', tagConfig);
        showAlert('保存成功');
    } catch (error) {
        showAlert('保存失败：' + error.message, 'danger');
        console.error('保存标签好友配置错误：', error);
    }
}

// 删除标签好友行
async function deleteTagFriendsRow(button) {
    const row = button.closest('tr');
    const tag = row.querySelector('.tag-select').value;
    
    // 从配置中删除
    if (tagConfig.tags_friends && tagConfig.tags_friends[tag]) {
        delete tagConfig.tags_friends[tag];
        
        try {
            // 保存到服务器
            await axios.post('/api/tag-config', tagConfig);
            showAlert('删除成功');
            
            // 从界面移除
            row.remove();
        } catch (error) {
            showAlert('删除失败：' + error.message, 'danger');
            console.error('删除标签好友配置错误：', error);
        }
    } else {
        // 如果配置中不存在，直接从界面移除
        row.remove();
    }
}

// 删除定时任务
async function deleteScheduledTask(button) {
    try {
        const row = button.closest('tr');
        if (!row) {
            showAlert('无法找到任务行', 'danger');
            return;
        }

        const taskId = row.querySelector('.task-id')?.textContent;
        if (!taskId) {
            row.remove();
            return;
        }

        // 调用删除任务API
        await axios.delete(`/api/tasks/${taskId}`);
        
        // 更新任务列表
        await updateScheduledTasksTable();
        
        showAlert('删除成功');
    } catch (error) {
        console.error('删除定时任务错误：', error);
        showAlert(error.response?.data?.error || '删除失败', 'danger');
    }
}

// 保存定时任务行
async function saveScheduledTaskRow(button) {
    try {
        const row = button.closest('tr');
        if (!row) {
            showAlert('无法找到任务行', 'danger');
            return;
        }

        const taskId = row.querySelector('.task-id')?.textContent;
        const tag = row.querySelector('.task-tag')?.value;
        const scheduleType = row.querySelector('.task-schedule-type')?.value;
        const time = row.querySelector('.task-time')?.value;
        const message = row.querySelector('.task-message')?.value;

        if (!tag || !scheduleType || !time || !message) {
            showAlert('请填写完整的任务信息', 'warning');
            return;
        }

        // 更新任务
        const task = {
            tag: tag,
            schedule_type: scheduleType,
            time: time,
            message: message
        };

        // 调用更新任务的API
        await axios.put(`/api/tasks/${taskId}`, task);
        
        // 立即刷新任务列表
        await updateScheduledTasksTable();
        
        // 立即检查任务状态
        checkTaskStatus();
        
        showAlert('保存成功', 'success');
    } catch (error) {
        console.error('保存定时任务错误：', error);
        showAlert(error.response?.data?.error || '保存失败', 'danger');
    }
}

// 更新标签设置区域的UI
function updateTagSettingsUI() {
    const container = document.querySelector('.tag-settings-container');
    if (!container) return;
    
    container.innerHTML = `
        <div class="card mb-3">
            <div class="card-header">
                <h5 class="mb-0">标签设置</h5>
            </div>
            <div class="card-body">
                <div class="mb-3">
                    <label class="form-label"><strong>已启用的标签：</strong></label>
                    <div class="tag-list mb-2">
                        <!-- 标签列表将动态插入这里 -->
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="addTag()">
                        <i class="fas fa-plus"></i> 添加标签
                    </button>
                </div>
                <div class="alert alert-info mt-3">
                    <h6 class="alert-heading mb-2">
                        <i class="fas fa-info-circle"></i> 标签管理使用说明
                    </h6>
                    <p class="mb-2">标签是对好友进行分组管理的重要工具，可用于群发消息和自动回复等功能。</p>
                    <hr>
                    <p class="mb-0">
                        <strong>【标签使用说明】</strong><br>
                        1. 管理员设置：<br>
                           - 在上方输入框中添加管理员微信昵称<br>
                           - 每行一个昵称<br>
                           - 管理员可以使用所有管理命令<br>
                        2. 标签设置：<br>
                           - 在下方输入框中添加可用的标签名称<br>
                           - 每行一个标签<br>
                           - 只有这些标签可以被使用<br>
                        3. 权限说明：<br>
                           - 管理员拥有所有权限<br>
                           - 普通用户权限由上方开关控制<br>
                           - 建议谨慎开放权限
                    </p>
                </div>
            </div>
        </div>
    `;
    
    // 更新标签列表
    updateTagList();
}

// 更新标签列表
async function updateTagList() {
    try {
        const response = await axios.get('/api/tag-config');
        const tagConfig = response.data;
        const tagList = document.querySelector('.tag-list');
        
        if (!tagList) return;
        
        // 清空现有标签
        tagList.textContent = '';  // 使用 textContent 清空内容
        
        // 添加每个标签
        tagConfig.enabled_tags.forEach(tag => {
            const tagElement = document.createElement('div');
            tagElement.className = 'tag-item mb-2 d-flex align-items-center';
            tagElement.innerHTML = `
                <span class="badge bg-primary me-2">${tag}</span>
                <button class="btn btn-outline-danger btn-sm" onclick="removeTag('${tag}')">
                    <i class="fas fa-times"></i>
                </button>
            `;
            tagList.appendChild(tagElement);
        });
        
        // 如果没有标签，显示提示
        if (tagConfig.enabled_tags.length === 0) {
            tagList.innerHTML = '<div class="text-muted">暂无标签</div>';
        }
        
    } catch (error) {
        console.error('加载标签配置失败：', error);
        showAlert('加载标签配置失败', 'danger');
    }
}

// 添加标签
async function addTag() {
    const dialogText = 
        '请输入新标签名称\n\n' +
        '【标签规则说明】\n' +
        '1. 标签名称不能为空\n' +
        '2. 长度限制：最多20个字符\n' +
        '3. 允许字符：中文、英文、数字、下划线\n' +
        '4. 系统限制：最多创建50个标签\n\n' +
        '温馨提示：标签创建后将立即生效，请谨慎操作';
    
    const newTag = prompt(dialogText);
    
    if (!newTag) return;
    
    try {
        await axios.post('/api/tags', { tag: newTag.trim() });
        showAlert('标签添加成功');
        updateTagList();
    } catch (error) {
        const errorMsg = error.response?.data?.error || '添加标签失败';
        showAlert(errorMsg, 'danger');
    }
}

// 删除标签
async function removeTag(tagName) {
    if (!confirm(`确定要删除标签"${tagName}"吗？`)) return;
    
    try {
        await axios.delete(`/api/tags/${encodeURIComponent(tagName)}`);
        showAlert('标签删除成功');
        updateTagList();
    } catch (error) {
        const errorMsg = error.response?.data?.error || '删除标签失败';
        showAlert(errorMsg, 'danger');
    }
}

// 检查任务状态
async function checkTaskStatus(retryCount = 0) {
    try {
        const response = await axios.get('/api/tasks/status');
        if (!response.data) {
            console.warn('任务状态数据为空');
            return;
        }
        
        const tasks = Array.isArray(response.data) ? response.data : [];
        const tbody = document.querySelector('#scheduledTasksTable tbody');
        if (!tbody) {
            console.warn('找不到任务表格');
            return;
        }
        
        // 更新现有任务的状态
        tasks.forEach(task => {
            if (!task || !task.id) {
                console.warn('无效的任务数据:', task);
                return;
            }
            
            const row = tbody.querySelector(`tr[data-task-id="${task.id}"]`);
            if (!row) {
                return; // 跳过不存在的任务行
            }
            
            // 更新状态列
            const statusCell = row.querySelector('td.task-status');
            if (statusCell) {
                const status = task.status || {};
                const isRunning = status.is_running || false;
                const lastExecution = status.last_execution || '从未运行';
                const nextRun = task.next_run || '未知';
                const successRate = ((status.success_count || 0) / Math.max(1, (status.total_attempts || 1)) * 100).toFixed(1);
                
                statusCell.innerHTML = `
                    <span class="badge ${isRunning ? 'bg-success' : 'bg-secondary'} me-2">
                        ${isRunning ? '运行中' : '等待中'}
                    </span>
                    <small class="text-muted">
                        上次运行: ${lastExecution}<br>
                        下次运行: ${nextRun}<br>
                        成功率: ${successRate}%
                    </small>
                `;
            }
        });
    } catch (error) {
        console.error('检查任务状态失败：', error.response?.data?.error || error.message || error);
        
        // 如果是插件未初始化的错误，并且重试次数小于3次，则等待5秒后重试
        if (error.response?.data?.error === 'Plugin not initialized' && retryCount < 3) {
            console.log(`将在5秒后重试（第${retryCount + 1}次）...`);
            setTimeout(() => checkTaskStatus(retryCount + 1), 5000);
            return;
        }
        
        // 不要在UI上显示错误，因为这是一个周期性的后台操作
    }
}

// 每30秒检查一次任务状态
let taskStatusInterval = setInterval(checkTaskStatus, 30000);

// 页面加载完成后立即执行一次
document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    checkTaskStatus(); // 立即检查一次任务状态
});