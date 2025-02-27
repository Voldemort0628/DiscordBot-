from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, FloatField, IntegerField, SubmitField, SelectField
from wtforms.validators import DataRequired, URL, Optional, IPAddress, NumberRange

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class StoreForm(FlaskForm):
    url = StringField('Store URL', validators=[DataRequired(), URL()])
    enabled = BooleanField('Enabled')
    submit = SubmitField('Add Store')

class KeywordForm(FlaskForm):
    word = StringField('Keyword', validators=[DataRequired()])
    enabled = BooleanField('Enabled')
    submit = SubmitField('Add Keyword')

class ConfigForm(FlaskForm):
    rate_limit = FloatField('Rate Limit (requests/second)', validators=[DataRequired()])
    monitor_delay = IntegerField('Monitor Delay (seconds)', validators=[DataRequired()])
    max_products = IntegerField('Max Products per Store', validators=[DataRequired()])
    submit = SubmitField('Save Configuration')

class VariantScraperForm(FlaskForm):
    product_url = StringField('Product URL', validators=[DataRequired(), URL()])
    submit = SubmitField('Scrape Variants')

class RetailScraperForm(FlaskForm):
    retailer = SelectField('Retailer', choices=[
        ('target', 'Target'),
        ('walmart', 'Walmart'),
        ('bestbuy', 'Best Buy')
    ], validators=[DataRequired()])
    keyword = StringField('Pokemon Keyword', validators=[DataRequired()])
    check_frequency = IntegerField('Check Frequency (seconds)', default=3600)
    enabled = BooleanField('Enabled', default=True)
    submit = SubmitField('Add Scraper')

class ProxyForm(FlaskForm):
    ip = StringField('IP Address', validators=[DataRequired(), IPAddress()])
    port = IntegerField('Port', validators=[DataRequired(), NumberRange(min=1, max=65535)])
    username = StringField('Username (Optional)', validators=[Optional()])
    password = PasswordField('Password (Optional)', validators=[Optional()])
    protocol = SelectField('Protocol', choices=[
        ('http', 'HTTP'),
        ('https', 'HTTPS'),
        ('socks5', 'SOCKS5')
    ], validators=[DataRequired()])
    country = StringField('Country Code (Optional)', validators=[Optional()])
    enabled = BooleanField('Enabled', default=True)
    submit = SubmitField('Add Proxy')

class ProxyImportForm(FlaskForm):
    proxy_list = StringField('Proxy List (One per line, format: ip:port:user:pass or ip:port)', 
                           validators=[DataRequired()])
    protocol = SelectField('Protocol', choices=[
        ('http', 'HTTP'),
        ('https', 'HTTPS'),
        ('socks5', 'SOCKS5')
    ], validators=[DataRequired()])
    submit = SubmitField('Import Proxies')