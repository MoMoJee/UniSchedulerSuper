from typing import Tuple, Any

from django.db import models
from django.contrib.auth.models import User
import json
import logging
import datetime
from django.db.utils import IntegrityError


logger = logging.getLogger("logger")

# 定义标准数据格式
DATA_SCHEMA = {
    # TODO 这里的 default 不能稳定工作
    # !!!!! 注意 dict 类型必须要嵌套到没有为止，dict 类型的 default 只要写一个 {} 即可 ！！！！！
    "ai_chatting": {
        "token_balance": {
            "type": int,
            "nullable": False,
            "default": 1000000,
        },
        "nickname": {
            "type": str,
            "nullable": False,
            "default": "",
        },
    },
    "events": {
        "type": list,
        "nullable": False,
        "default": [],
        "items": {  # 如果是列表，定义列表中每个元素的格式
            "id": {
                "type": str,
                "nullable": False,
            },
            "title": {
                "type": str,
                "nullable": False,
            },
            "start": {
                "type": str,
                "nullable": False,
            },
            "end": {
                "type": str,
                "nullable": False,
            },
            "description": {
                "type": str,
                "nullable": True,
                "default": "",
            },
            "importance": {
                "type": str,
                "nullable": True,
                "default": "",
            },
            "urgency": {
                "type": str,
                "nullable": True,
                "default": "",
            },
            "groupID": {
                "type": str,
                "nullable": False,
            },
            "ddl": {
                "type": str,
                "nullable": False,
                "default": "",
            },
            "last_modified": {
                "type": str,
                "nullable": False,
                "default": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        },
    },
    "events_groups": {
        "type": list,
        "nullable": False,
        "default": [],
        "items": {
            "id": {
                "type": str,
                "nullable": False,
            },
            "name": {
                "type": str,
                "nullable": False,
            },
            "description": {
                "type": str,
                "nullable": True,
                "default": "",
            },
            "color": {
                "type": str,
                "nullable": False,
                "default": "#000000",  # 默认颜色
            },
        },
    },
    "user_settings": {
        "type": list,
        "nullable": False,
        "default": [],
        "items": {
            "now_view": {
                "type": dict,
                "nullable": False,
                "default": {},
                "items": {
                    "viewType": {
                        "type": str,
                        "nullable": False,
                        "default": "timeGridWeek",
                    },
                    "start": {
                        "type": str,
                        "nullable": False,
                        "default": datetime.datetime.now().isoformat(),
                    },
                    "end": {
                        "type": str,
                        "nullable": False,
                        "default": (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat(),
                    },
                },
            },
        },
    },
    "planner": {
        "type": dict,
        "nullable": False,
        "default": {},
        "items": {
            "dialogue": {
                "type": list,
                "nullable": False,
                "default": [],
            },
            "temp_events": {
                "type": list,
                "nullable": False,
                "default": [],
                "items": {
                    "id": {
                        "type": str,
                        "nullable": False,
                    },
                    "title": {
                        "type": str,
                        "nullable": False,
                    },
                    "start": {
                        "type": str,
                        "nullable": False,
                    },
                    "end": {
                        "type": str,
                        "nullable": False,
                    },
                    "description": {
                        "type": str,
                        "nullable": True,
                        "default": "",
                    },
                    "importance": {
                        "type": str,
                        "nullable": True,
                        "default": "",
                    },
                    "urgency": {
                        "type": str,
                        "nullable": True,
                        "default": "",
                    },
                    "groupID": {
                        "type": str,
                        "nullable": False,
                    },
                    "ddl": {
                        "type": str,
                        "nullable": True,
                        "default": "",
                    },
                },
            },
            "ai_planning_time": {
                "type": dict,
                "nullable": False,
                "default": {},
                "items": {
                    "start": {
                        "type": str,
                        "nullable": False,
                        "default": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    "end": {
                        "type": str,
                        "nullable": False,
                        "default": (datetime.datetime.now() + datetime.timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    },
                },
            },
        },
    },
    "setting": {
        "type": dict,
        "nullable": False,
        "default": {},
        "items": {
            "AI_setting_code": {
                "type": int,
                "nullable": False,
                "default": 2,
            },
        },
    },
    "outport_calendar_data": {
        "type": dict,
        "nullable": False,
        "default": {},
        "items": {
            "sent_events_uuid": {
                "type": list,
                "nullable": False,
                "default": [],  # TODO 列表类型的检查有问题，只能处理列表内直接嵌套字典的，去看 events 的就知道了。so 不要 check
            },
            "last_sent_time": {
                "type": str,
                "nullable": False,
                "default": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        },
    },
    "user_preference": {
        "type": dict,
        "nullable": False,
        "default": {},
        "items": {
            "week_number_start": {
                "type": dict,
                "nullable": False,
                "default":  {},
                "items": {
                    "month":{
                        "type": int,
                        "nullable": False,
                        "default": 1,
                    },
                    "day":{
                        "type": int,
                        "nullable": False,
                        "default": 1,
                    },
                },
            },
            "auto_ddl": {
                # TODO 布尔值的检查会出现 if <bool> 的愚蠢错误
                "type": bool,
                "nullable": True,
                "default": True,
            },
        },
    },
}
# 这里定义用户信息类

'''
定义一个 UserProfile 模型来存储用户额外信息是一种非常常见且推荐的方式。
Django 默认的用户模型（django.contrib.auth.models.User）已经提供了基本的用户信息字段，如用户名、密码、邮箱等。
然而，在实际应用中，我们通常需要存储更多用户相关的额外信息，例如电话号码、地址、头像等。通过扩展默认的用户模型，可以方便地实现这一需求。
'''
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    date_joined = User.date_joined
    # phone_number = models.CharField(max_length=15, blank=True)
    # address = models.TextField(blank=True)
    # avatar = models.ImageField(upload_to='avatars/', blank=True)

    def __str__(self):
        return f"Profile of {self.user.username}"
# UserProfile 模型通常用于存储与用户相关的额外信息。
# Django 的默认 User 模型已经包含了基本的用户信息（如用户名、密码、邮箱等），
# 但有时你可能需要存储更多用户相关的数据，比如电话号码、地址、头像等。
#一对一关系：通过 OneToOneField 将 UserProfile 与 User 模型关联起来，确保每个用户只有一个对应的 UserProfile。
# 便于管理：可以在 Django Admin 中方便地管理用户及其额外信息。



class UserData(models.Model):
    # 这里定义用户数据模型，
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    value = models.TextField()
    # 使用 TextField 存储序列化后的数据。python自带的SQLite不支持JSON格式，因此下面有一套解析函数

    # def __init__(self, *args, **kwargs):
    #     self.request = kwargs.pop('request', None)
    #     self.user = kwargs.pop('user', None)
    #     self.new_key = kwargs.pop('new_key', None)
    #     self.data = kwargs.pop('data', None)
    #     super().__init__(*args, **kwargs)
    #     if self.request and self.new_key:
    #         self.init_key(self.request, self.new_key, self.data)


    def __str__(self):
        return f"{self.user.username} - {self.key}"

    @classmethod
    def get_or_initialize(cls, request, new_key, data=None)-> tuple[None, bool, dict[str, str]] | tuple[
        'UserData', bool, dict[str, str]]:
        """
        获取或初始化用户数据（通过key）。

        参数：
        - request: 请求对象，用于获取当前用户。
        - new_key: 要获取或初始化的key名称。
        - data: 要写入的数据，默认为None。如果为None，则使用DATA_SCHEMA中的默认值。

        返回：
        - 一个元组，包含 UserData 实例和一个布尔值，表示是否创建了新实例。
        - 一个包含状态和消息的字典。

        调用：
        user_data, created, result = UserData.get_or_initialize(
        request=request,
        new_key=<>,
        )
        """


        # 确保用户已登录
        if not request.user.is_authenticated:
            return None, False, {"status": "error", "message": "User is not authenticated."}

        # 检查key是否已经在用户数据中存在
        try:
            existing_data = cls.objects.get(user=request.user, key=new_key)
            return existing_data, False, {"status": "success", "message": f"Key <{new_key}> already exists in user data."}
        except cls.DoesNotExist:
            pass

        # 检查DATA_SCHEMA变量中是否有定义该key
        if new_key not in DATA_SCHEMA:
            logger.warning(f"Key <{new_key}> not defined in DATA_SCHEMA. Please define it first.")
            return None, False, {"status": "error", "message": f"Key <{new_key}> not defined in DATA_SCHEMA. Please define it first."}

        # 获取对应的schema
        schema = DATA_SCHEMA[new_key]

        # 检查用户要写入的数据并执行一次检查
        if data is None:
            data = schema.get("default", {})

        # 验证和初始化数据
        validated_data = cls().validate_and_initialize_data(data, schema)

        # 在用户数据中创建这个新的key
        try:
            new_data = cls.objects.create(user=request.user, key=new_key, value=json.dumps(validated_data))
            return new_data, True, {"status": "success", "message": f"Key <{new_key}> added successfully."}
        except IntegrityError:
            logger.error(f"Failed to add key <{new_key}>: IntegrityError")
            return None, False, {"status": "error", "message": f"Failed to add key <{new_key}>: IntegrityError"}
        except Exception as e:
            logger.error(f"Failed to add key <{new_key}>: {str(e)}")
            return None, False, {"status": "error", "message": f"Failed to add key <{new_key}>: {str(e)}"}


    def init_key(self, request, new_key, data=None):
        """
        较早期的初始化函数，可以用于查询或生成只读的 UserData 的 key - 查询值
        对于需要执行数据修改的需要，请使用 get_or_initialize 方法

        参数：
        - request: 请求对象，用于获取当前用户。
        - new_key: 要初始化的key名称。
        - data: 要写入的数据，默认为None。如果为None，则使用DATA_SCHEMA中的默认值。
    
        返回：
        - 一个包含状态和消息的字典。
        """

        # 检查key是否已经在用户数据中存在
        try:
            existing_data = UserData.objects.get(user=request.user, key=new_key)
            self.value = existing_data.value
            return {"status": "success", "message": f"Key <{new_key}> already exists in user data.", "value": existing_data}
        except UserData.DoesNotExist:
            pass

        # 检查DATA_SCHEMA变量中是否有定义该key
        if new_key not in DATA_SCHEMA:
            logger.warning(f"Key <{new_key}> not defined in DATA_SCHEMA. Please define it first.")
            return {"status": "error", "message": f"Key <{new_key}> not defined in DATA_SCHEMA. Please define it first."}
        # 获取对应的schema
        schema = DATA_SCHEMA[new_key]

        # 检查用户要写入的数据并执行一次检查
        if data is None:
            data = schema.get("default", {})

        # 验证和初始化数据
        validated_data = self.validate_and_initialize_data(data, schema)

        # 在用户数据中创建这个新的key
        try:
            user_data, created = UserData.objects.get_or_create(
                user=request.user,
                key=new_key,
                defaults={"value": json.dumps(validated_data)}
            )
            if created:
                self.value = json.dumps(validated_data)
                return {"status": "success", "message": f"Key <{new_key}> added successfully."}
            else:
                return {"status": "success", "message": f"Key <{new_key}> already exists in user data.", "value": user_data}
        except IntegrityError:
            logger.error(f"Failed to add key <{new_key}>: IntegrityError")
            return {"status": "error", "message": f"Failed to add key <{new_key}>: IntegrityError"}
        except Exception as e:
            logger.error(f"Failed to add key <{new_key}>: {str(e)}")
            return {"status": "error", "message": f"Failed to add key <{new_key}>: {str(e)}"}


    def set_value(self, data, check=False)->None:
        # 在设置值之前，先验证和初始化数据
        schema = DATA_SCHEMA.get(str(self.key))
        if check:
            if schema:
                data = self.validate_and_initialize_data(data, schema)
            else:
                logger.warning(f"{self.key}是未经DATA_SCHEMA定义的key，要先对DATA_SCHEMA执行修改")

                return

        self.value = json.dumps(data)
        self.save()

    def get_value(self, check=False)->dict:
        if not self.value:
            return {}
        try:
            data = json.loads(self.value)
            # 在获取值时，也可以选择验证和初始化
            schema = DATA_SCHEMA.get(str(self.key))
            if check:
                if schema:
                    data = self.validate_and_initialize_data(data, schema)
                else:
                    logger.warning(f"{self.key}是未经 DATA_SCHEMA 定义的 key，要先对 DATA_SCHEMA 执行修改")
                    return {}

            return data
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            return {}

    def validate_and_initialize_data(self, data, schema):
        """
        根据 schema 验证和初始化数据。
        如果数据不符合 schema，将根据 schema 的默认值进行初始化。
        """
        if not data:
            return schema.get("default", {})

        # 如果数据类型不匹配，直接返回默认值
        if not isinstance(data, schema.get("type", type(data))):
            return schema.get("default", {})

        # 如果是基本类型（如 int, str），直接验证
        if schema.get("type") in (int, str, bool, float):
            if schema.get("nullable") and data is None:
                return data
            if not schema.get("nullable") and data is None:
                return schema.get("default", {})
            return data

        # 如果是列表类型
        if schema.get("type") == list:
            if not isinstance(data, list):
                return schema.get("default", [])
            validated_list = []
            for item in data:
                if not isinstance(item, dict):
                    # 如果列表中的元素不是字典，直接跳过
                    continue
                validated_item = {}
                for field, field_schema in schema.get("items", {}).items():
                    field_value = item.get(field)
                    validated_item[field] = self.validate_and_initialize_data(field_value, field_schema)
                validated_list.append(validated_item)
            return validated_list

        # 如果是字典类型
        if schema.get("type") == dict:
            if not isinstance(data, dict):
                return schema.get("default", {})
            validated_data = {}
            for field, field_schema in schema.get("items", {}).items():
                field_value = data.get(field)
                validated_data[field] = self.validate_and_initialize_data(field_value, field_schema)
            return validated_data

        return data
    # 于是，我们创建了用户模型，通过字符串的key+JSON格式的value存储，其中value如果是非文本类型，是需要额外解析的。为了统一，这里推荐全部解析使用。


# UserData 模型通常用于存储用户动态生成的数据，这些数据可能因用户而异，且可能需要频繁更新或扩展。例如，用户在某个应用中生成的配置数据、记录的数据等
# 动态数据存储：存储用户生成的动态数据，这些数据可能因用户而异，且可能需要频繁更新。
# 多对一关系：通过 ForeignKey 将 UserData 与 User 模型关联起来，允许每个用户有多个数据记录。
# 灵活扩展：可以通过添加新的 key 来扩展数据结构，而无需修改数据库表结构。


# TODO 协作数据类型
class CollaborativeEventGroup(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class CollaborativeEvent(models.Model):
    group = models.ForeignKey(CollaborativeEventGroup, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title