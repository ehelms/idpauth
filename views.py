from django.shortcuts import render_to_response
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext
from django import forms
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import authenticate, login

import ldap
import os
import urllib

import openid   
from openid.consumer.consumer import Consumer, \
    SUCCESS, CANCEL, FAILURE, SETUP_NEEDED
from openid.consumer.discover import DiscoveryFailure



from idpauth import user_tools
from idpauth.models import IdentityProvider, IdentityProviderLDAP, Role
from idpauth import openid_tools

from vdi.log import log

def login(request, institution):
    institutional_IdP = IdentityProvider.objects.filter(institution__iexact=str(institution))

    if not institutional_IdP:
        log.debug("No institution")
        return HttpResponse("There is no Identity Provider specified for your institution")
    else:
        authentication_type = institutional_IdP[0].type
        return render_to_response(str(authentication_type)+'.html',
        {'institution': institution,},
        context_instance=RequestContext(request))

def ldap_login(request):
    #TODO: What if one of these 3 fields aren't set?
    username = request.POST['username']
    password = request.POST['password']
    institution = request.POST['institution']

    # @TODO resolve upper vs. lower case storage of key field like institution
    server = IdentityProviderLDAP.objects.filter(institution=str(institution).upper())[0]
    result_set = []
    timeout = 0

    try:
        #TODO: Make this work with ldap servers that aren't ldap.ncsu.edu
        ldap_session = ldap.initialize(server.url)
        ldap_session.start_tls_s()
        ldap_session.protocol_version = ldap.VERSION3
        # Any errors will throw an ldap.LDAPError exception
        # or related exception so you can ignore the result
        ldap_session.set_option(ldap.OPT_X_TLS_DEMAND, True)
        search_string = "uid=" + username
        authentication_string = search_string + "," +  server.authentication
        ldap_session.simple_bind_s(authentication_string, password)
        result_id = ldap_session.search(server.authentication,ldap.SCOPE_SUBTREE,search_string,["memberNisNetgroup"])
        while 1:
            result_type, result_data = ldap_session.result(result_id, timeout)
            if (result_data == []):
                break
            else:
                if result_type == ldap.RES_SEARCH_ENTRY:
                    result_set.append(result_data)
        log.debug(result_set)
        #if you got here then the right password has been entered for the user
        roles = result_set[0][0][1]['memberNisNetgroup']
        log.debug(roles)
        user_tools.login(request, username, roles, institution)
        log.debug("Redirecting to vdi")
        return HttpResponseRedirect('/vdi/')
    except ldap.LDAPError, e:
        #TODO: Handle login error
        log.debug(e)
        return login(request, institution)

def openid_login(request):
    openid_url = request.POST['openid_url']
    institution = request.POST['institution']

    consumer = Consumer(request.session, openid_tools.DjangoOpenIDStore())

    try:
        auth_request = consumer.begin(openid_url)
    except DiscoveryFailure:
        return HttpResponse('The OpenID was invalid')

    trust_root =  openid_tools.get_url_host(request) + '/'
    redirect_to = openid_tools.get_url_host(request) + '/vdi/openid_login_complete/'

    redirect_url = auth_request.redirectURL(trust_root, redirect_to)
 
    return HttpResponseRedirect(redirect_url)

def openid_login_complete(request):

    consumer = Consumer(request.session, openid_tools.DjangoOpenIDStore())

    url = (openid_tools.get_url_host(request) + '/vdi/openid_login_complete/').encode('utf8') + '?janrain_nonce=' + urllib.pathname2url(request.GET['janrain_nonce'])
    query_dict = dict([
        (k.encode('utf8'), v.encode('utf8')) for k, v in request.GET.items()
    ])

    openid_response = consumer.complete(query_dict, url)

    if openid_response.status == SUCCESS:
        user_tools.login(request, "null", 'T', "null")
        return HttpResponseRedirect('/vdi/')
    else:
        return HttpResponse(str(openid_response.message))
    
def local_login(request):

    username = request.POST['username']
    password = request.POST['password']
    institution = request.POST['institution']
    user = authenticate(username=username, password=password)

    roles = 'T'

    if user is not None:
        if user.is_active:
            user_tools.login(request, username, roles, institution)
            return HttpResponseRedirect('/vdi/')
    else:
        return login(request, institution)

@user_tools.login_required
def logout(request):
    session_institution = request.session["institution"]
    user_tools.logout(request)
    return HttpResponseRedirect('/vdi/login/'+str(session_institution))
