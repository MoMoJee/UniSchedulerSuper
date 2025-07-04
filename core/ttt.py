dialogue = [
        {"role": "system",
         "content": ("你是用户日程生成偏好设定助手。给定原有场景preset（json形式），以及用户的新反馈（用户不满意的地方与新诉求），请结合两者，对preset的need/do_not/other_info三组内容做【合理的增删改】，生成最终新preset。"
                     "尤其要注意：如果用户的喜好变了（如从晚上换到早上），请彻底替换相关字段，而非简单添加。")},
        {"role": "user", "content": f"【用户反馈】："},
        {"role": "system",
         "content": (
             "你是用户日程生成偏好设定助手。给定原有场景preset（json形式），以及用户的新反馈（用户不满意的地方与新诉求），请结合两者，对preset的need/do_not/other_info三组内容做【合理的增删改】，生成最终新preset。"
             "尤其要注意：如果用户的喜好变了（如从晚上换到早上），请彻底替换相关字段，而非简单添加。")},
        {"role": "user", "content": f"【用户反馈】：122"}
    ]

user_prompts = [sentence['content'] if sentence['role'] == 'user' else "" for sentence in dialogue]
user_prompts = [prompt for prompt in user_prompts if prompt]
user_prompts_str = "\n".join(user_prompts)
print(user_prompts_str)