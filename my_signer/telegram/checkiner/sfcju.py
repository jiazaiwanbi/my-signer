from ._templ_a import TemplateACheckin


class SFCJUCheckin(TemplateACheckin):
    name = "非越助手"
    # Keep the endpoint used by the existing deployment; upstream later renamed it.
    bot_username = "fyemby_bot"
    bot_use_captcha = False
