from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, FloatField, IntegerField, SubmitField
from wtforms.validators import DataRequired, URL, Optional

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
