"""
Help text for SmsGatewayTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "SmsGatewayTab"

HELP_TEXT = """\
<h2>SMS gateway</h2>
<p>
This page is in <b>Controls</b>. It is where a live alarm sends a text.
The number and the gateway used to live under Setup &amp; Info; they are
the same saved settings, just on their own page.</p>
<p>
<b>Text alarms to this phone</b> has to be ticked or alarms stay silent on
the phone. A rule on <b>Alarm defs</b> can still choose a text, a desktop
alert, or both. If that rule says nothing about channels, this tick and the
desktop tick in Setup &amp; Info decide.</p>
<p>
<b>Gateway</b> is either <b>HTTP</b> or <b>Twilio</b>. HTTP posts JSON
(<code>to</code> and <code>message</code>) to the address you give, and puts
the token in <code>Authorization: Bearer</code> when one is set. Twilio uses
Twilio’s Messages API, so it needs the From number and the account SID.</p>
<p>
Leave <b>Token</b> blank to use <code>SMS_GATEWAY_TOKEN</code> from
secrets.env. Leave the Twilio account SID blank to use
<code>SMS_TWILIO_SID</code> the same way. The number must start with
<b>+</b> and the country code, for example +447700900123.</p>
<p>
<b>Save</b> writes the gateway. The next alarm text uses it.
<b>Test SMS</b> saves, then sends one message straight away, even if the
tick box is off, so you can check the path before an alarm needs it.
Texts use the same repeat timing as the desktop pop-up, so a standing alarm
does not text on every refresh.</p>
"""
