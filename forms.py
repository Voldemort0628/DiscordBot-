from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, FloatField, IntegerField, SubmitField, SelectField, TextAreaField
from wtforms.validators import DataRequired, URL, Optional, IPAddress, NumberRange, EqualTo, Length, ValidationError
from models import User

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', 
        validators=[DataRequired(), EqualTo('password', message='Passwords must match')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken. Please choose another one.')

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
    discord_webhook_url = StringField('Discord Webhook URL', validators=[Optional(), URL()])
    use_proxies = BooleanField('Use Proxies', default=False)
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

class ProxyImportForm(FlaskForm):
    proxy_list = TextAreaField('Proxy List (One proxy per line)',
                           validators=[DataRequired()],
                           description='Format: ip:port:username:password or ip:port. Example: 167.253.103.2:43929:b6zIPTgA:q1qqilpp')
    protocol = SelectField('Protocol', choices=[
        ('http', 'HTTP'),
        ('https', 'HTTPS'),
        ('socks5', 'SOCKS5')
    ], validators=[DataRequired()])
    submit = SubmitField('Import Proxies')