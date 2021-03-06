""" reset password form """
import ptah.form
import ptah.renderer
from datetime import datetime
from pyramid import security
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound
from pyramid.decorator import reify

import ptah
from ptah.password import PasswordSchema
from ptah.events import ResetPasswordInitiatedEvent
from ptah.events import PrincipalPasswordChangedEvent

from ptahcrowd import const
from ptahcrowd.schemas import ResetPasswordSchema
from ptahcrowd.settings import _


@view_config(
    route_name='ptahcrowd-resetpassword',
    renderer=ptah.renderer.layout('ptahcrowd:resetpassword.lt', 'ptahcrowd'))

class ResetPassword(ptah.form.Form):

    fields = ResetPasswordSchema

    def form_content(self):
        return {'login': self.request.params.get('login', '')}

    def update(self):
        cfg = ptah.get_settings(ptah.CFG_ID_PTAH, self.request.registry)
        self.from_name = cfg['email_from_name']
        self.from_address = cfg['email_from_address']

        return super(ResetPassword, self).update()

    @ptah.form.button(_('Start password reset'),
                      name='reset', actype=ptah.form.AC_PRIMARY)
    def reset(self):
        request = self.request
        data, errors = self.extract()

        login = data.get('login')
        if login:
            principal = ptah.auth_service.get_principal_bylogin(login)

            if principal is not None and \
                   ptah.pwd_tool.can_change_password(principal):
                passcode = ptah.pwd_tool.generate_passcode(principal)

                template = ResetPasswordTemplate(
                    principal, request, passcode=passcode)
                template.send()

                self.request.registry.notify(
                    ResetPasswordInitiatedEvent(principal))

                self.request.add_message(const.PASSWORD_RESET_START, 'success')
                return HTTPFound(location=request.application_url)

        self.request.add_message(_("The system can't restore the password for this user."), 'error')

    @ptah.form.button(_('Cancel'))
    def cancel(self):
        return HTTPFound(location=self.request.application_url)


@view_config(
    route_name='ptahcrowd-resetpassword-form',
    renderer=ptah.renderer.layout('ptahcrowd:resetpasswordform.lt', 'ptahcrowd'))

class ResetPasswordForm(ptah.form.Form):

    fields = PasswordSchema

    @reify
    def passcode(self):
        passcode = None
        if self.request.subpath:
            passcode = self.request.subpath[0]
        return passcode

    @reify
    def principal(self):
        principal = None
        if self.passcode:
            principal = ptah.pwd_tool.get_principal(self.passcode)
        else:
            principal = ptah.auth_service.get_current_principal()
        return principal
        

    def update(self):
        principal = self.principal
        if principal and ptah.pwd_tool.can_change_password(principal):
            return super(ResetPasswordForm, self).update()
        else:
            if self.passcode:
                self.request.add_message(_("Passcode is invalid."), 'warning')
            return HTTPFound(
                location='%s/resetpassword.html' % self.request.application_url)

    @ptah.form.button(_("Change password"),
                      name='change', actype=ptah.form.AC_PRIMARY)
    def changePassword(self):
        data, errors = self.extract()

        if errors:
            self.add_error_message(errors)
        else:
            principal = self.principal
            passcode = self.passcode
            if principal and not passcode:
                passcode = ptah.pwd_tool.generate_passcode(principal)
            ptah.pwd_tool.change_password(passcode, data['password'])

            self.request.registry.notify(
                PrincipalPasswordChangedEvent(principal))

            # check if principal can be authenticated
            info = ptah.auth_service.authenticate_principal(principal)

            headers = []
            if info.status:
                headers = security.remember(self.request, info.__uri__)

            self.request.add_message(
                _('You have successfully changed your password.'), 'success')
            return HTTPFound(
                headers=headers,
                location=self.request.application_url)


class ResetPasswordTemplate(ptah.mail.MailTemplate):

    subject = const.PASSWORD_RESET_SUBJECT
    template = 'ptahcrowd:resetpasswordmail.lt'

    def update(self):
        super(ResetPasswordTemplate, self).update()

        request = self.request

        self.date = datetime.now()

        remoteAddr = request.environ.get('REMOTE_ADDR', '')
        forwardedFor = request.environ.get('HTTP_X_FORWARDED_FOR', None)

        self.from_ip = (forwardedFor and '%s/%s' %
                        (remoteAddr, forwardedFor) or remoteAddr)

        self.url = '%s/resetpassword.html/%s/' % (
            request.application_url, self.passcode)

        info = self.context

        self.to_address = ptah.mail.formataddr((info.name, info.email))

