"""章标题由系统盖章:阿拉伯数字「第N章 标题」,写手不得写入正文。"""


def chapter_heading(order_index: int, title: str) -> str:
    cleaned = title.strip()
    if order_index < 1:
        return cleaned
    return f"第{order_index}章 {cleaned}".rstrip()
