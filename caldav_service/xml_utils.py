"""
CalDAV XML 工具模块

负责构建 WebDAV/CalDAV 响应所需的 XML，以及解析客户端发送的 XML 请求体。
"""

import xml.etree.ElementTree as ET

# =====================================================
# XML 命名空间
# =====================================================

NS_DAV = "DAV:"
NS_CALDAV = "urn:ietf:params:xml:ns:caldav"
NS_CS = "http://calendarserver.org/ns/"      # Apple Calendar Server 扩展
NS_ICAL = "http://apple.com/ns/ical/"        # Apple iCal 扩展

NSMAP = {
    "D": NS_DAV,
    "C": NS_CALDAV,
    "CS": NS_CS,
    "IC": NS_ICAL,
}


def _tag(ns: str, local: str) -> str:
    """构造 Clark notation 标签：{namespace}localname"""
    return f"{{{ns}}}{local}"


# 快捷标签构造
def dav(local: str) -> str:
    return _tag(NS_DAV, local)


def caldav(local: str) -> str:
    return _tag(NS_CALDAV, local)


def cs(local: str) -> str:
    return _tag(NS_CS, local)


def ical(local: str) -> str:
    return _tag(NS_ICAL, local)


# =====================================================
# XML 构建辅助
# =====================================================

def make_multistatus() -> ET.Element:
    """创建 <D:multistatus> 根元素，注册所有命名空间前缀。"""
    root = ET.Element(dav("multistatus"))
    for prefix, uri in NSMAP.items():
        root.set(f"xmlns:{prefix}", uri)
    return root


def add_response(parent: ET.Element, href: str) -> ET.Element:
    """在 multistatus 下添加一个 <D:response>。"""
    resp = ET.SubElement(parent, dav("response"))
    href_el = ET.SubElement(resp, dav("href"))
    href_el.text = href
    return resp


def add_propstat(response: ET.Element, status: str = "HTTP/1.1 200 OK") -> ET.Element:
    """在 response 下添加 <D:propstat>，包含 <D:prop> 和 <D:status>。"""
    propstat = ET.SubElement(response, dav("propstat"))
    ET.SubElement(propstat, dav("prop"))
    status_el = ET.SubElement(propstat, dav("status"))
    status_el.text = status
    return propstat


def get_prop(propstat: ET.Element) -> ET.Element:
    """从 propstat 中取出 <D:prop> 元素。"""
    return propstat.find(dav("prop"))


def set_text_prop(prop: ET.Element, tag: str, text: str):
    """在 <D:prop> 中添加一个文本子元素。"""
    el = ET.SubElement(prop, tag)
    el.text = text


def set_href_prop(prop: ET.Element, tag: str, href: str):
    """在 <D:prop> 中添加含 <D:href> 的子元素。"""
    wrapper = ET.SubElement(prop, tag)
    href_el = ET.SubElement(wrapper, dav("href"))
    href_el.text = href


def serialize_xml(root: ET.Element) -> bytes:
    """将 ElementTree 元素序列化为 UTF-8 XML 字节串。"""
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")


# =====================================================
# XML 解析辅助
# =====================================================

def parse_xml_body(body: bytes) -> ET.Element:
    """安全解析请求体中的 XML。"""
    return ET.fromstring(body)


def get_local_name(tag: str) -> str:
    """从 Clark notation 中提取本地名。"""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_requested_props(body: bytes):
    """
    从 PROPFIND 请求体中提取客户端请求的属性列表。
    如果请求体为空或包含 <D:allprop/>，返回 None（表示返回所有属性）。
    """
    if not body or not body.strip():
        return None  # allprop
    root = parse_xml_body(body)
    # 查找 <D:allprop/>
    if root.find(dav("allprop")) is not None:
        return None
    # 查找 <D:prop> 下的所有子元素
    prop_el = root.find(dav("prop"))
    if prop_el is None:
        return None
    return [child.tag for child in prop_el]
