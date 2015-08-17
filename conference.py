#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from google.net.proto.ProtocolBuffer import ProtocolBufferDecodeError

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize

# ============================================
# MY IMPORT ADDITIONS ========================

import logging

from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionTypes

from models import Speaker
from models import SpeakerForm
from models import SpeakerForms

# END OF MY IMPORT ADDITIONS =================
# ============================================

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_CONF_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1)
)

# ============================================
# MY RESOURCE CONTAINER ADDITIONS ============

SESSION_GET_SPEAKER_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSpeakerKey=messages.StringField(1)
)

SESSION_POST_CONF_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1)
)

SESSION_GET_CONF_REQUEST_WITH_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.EnumField(SessionTypes, 2)
)

SESSION_GET_SESSION_SPEAKER_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speakerName=messages.StringField(1)
)

SESSION_POST_WISHLIST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1)
)

SESSION_GET_CONF_REQUEST_WITH_DATE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    startDate=messages.StringField(2),
    endDate=messages.StringField(3)
)

SESSION_GET_CONF_REQUEST_WITH_TIME = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    startTime=messages.IntegerField(2),
    endTime=messages.IntegerField(3)
)

SESSION_GET_CONF_REQUEST_PICKY = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    antiTypeOfSession=messages.EnumField(SessionTypes, 2),
    latestTime=messages.IntegerField(3)
)

SESSION_GET_FEATURED_SPEAKER_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1)
)

# END OF MY RESOURCE CONTAINER ADDITIONS =====
# ============================================

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

    # ============================================
    # MY HELPER FUNCTION ADDITIONS ===============

    @staticmethod
    def _getKeyAndEntityFromWebsafeKeyOfType(websafeKey, entityKind):
        """Gets a Key and entity from a given websafeKey string. This checks that the key is both valid, contains an entity and is of type entityKind."""

        # get the Key
        try:
            key = ndb.Key(urlsafe=websafeKey)
        except (ProtocolBufferDecodeError, TypeError):
            raise endpoints.BadRequestException("Invalid key: %s" % websafeKey)

        # get the entity
        entity = key.get()
        if not entity:
            raise endpoints.NotFoundException('No entity found with key: %s' % websafeKey)

        # check type of entity
        if type(entity) != entityKind:
            raise endpoints.BadRequestException('Key %s refers to an entity that is not of type %s' % (websafeKey, entityKind.__name__))

        return key, entity

    @staticmethod
    def _getKeyFromWebsafeKey(websafeKey):
        """Gets a Key from a given websafeKey string. This only checks that the key is valid but not whether it actually contains an entity"""

        # get the Key
        try:
            key = ndb.Key(urlsafe=websafeKey)
        except (ProtocolBufferDecodeError, TypeError):
            raise endpoints.BadRequestException("Invalid key: %s" % websafeKey)

        return key

    @staticmethod
    def _getUserId():
        """Return user id of current logged in user. Raise UnauthorizedException if user is not logged in.
        Declared as static so that any static cron/task methods can call it."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        return getUserId(user)

    # END OF MY HELPER FUNCTION ADDITIONS ========
    # ============================================

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )

    # ============================================
    # MY TASK 1 ADDITIONS ========================

    # NOTE: I have modeled speakers as an entity instead of just a name string so that:
    # 1) it is possible to have additional info about them (e.g. bio)
    # 2) it is easier to update info about them at one single location and have the updated info show up everywhere

# - - - Speaker objects - - - - - - - - - - - - - - - - - - -

    def _copySpeakerToForm(self, speaker):
        """Copy relevant fields from Speaker to SpeakerForm"""

        # create a new entity first
        sf = SpeakerForm()

        # convert Speaker properties to SpeakerForm fields
        sf.name = speaker.name
        sf.bio = speaker.bio
        sf.websafeKey = speaker.key.urlsafe()

        # check and return
        sf.check_initialized()
        return sf

    def _copySpeakersToForms(self, speakers):
        """Return SpeakerForms from a given Speaker array"""
        return SpeakerForms(
            items = [self._copySpeakerToForm(speaker) for speaker in speakers]
        )

    @endpoints.method(SpeakerForm, SpeakerForm,
            path='speaker',
            http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker"""

        # check for required fields
        if not request.name:
            raise endpoints.BadRequestException("Speaker 'name' field required")

        # create speaker
        speaker = Speaker(
            name = request.name.title(),  #store in fixed title case for case-independent string request later
            bio = request.bio
        )
        speaker.put()

        # return SpeakerForm
        return self._copySpeakerToForm(speaker)

    @endpoints.method(SESSION_GET_SPEAKER_REQUEST, SpeakerForm,
            path='speaker/{websafeSpeakerKey}',
            http_method='GET', name='getSpeaker')
    def getSpeaker(self, request):
        """Return speaker"""

        # get Speaker object using key
        speakerKey, speaker = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeSpeakerKey, Speaker)

        # return SpeakerForm
        return self._copySpeakerToForm(speaker)

# - - - Session objects - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm"""

        # create a new entity first
        sf = SessionForm()

        # convert Session properties to SessionForm fields
        sf.name = session.name
        sf.highlights = session.highlights
        sf.speakerKeys = session.speakerKeys
        sf.duration = session.duration
        sf.typeOfSession = getattr(SessionTypes, session.typeOfSession)
        sf.date = str(session.date)
        sf.startTime = int('%s%s' % (str(session.startTime)[:2], str(session.startTime)[3:5]))
        sf.websafeKey = session.key.urlsafe()

        # check and return
        sf.check_initialized()
        return sf

    def _copySessionsToForms(self, sessions):
        """Return SessionForms from a given Session array"""
        return SessionForms(
            items = [self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESSION_GET_CONF_REQUEST, SessionForms,
            path='session/{websafeConferenceKey}',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return all sessions of a given conference"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # get sessions of this conference
        sessions = Session.query(ancestor=confKey)

        # return SessionForms
        return self._copySessionsToForms(sessions)

    @endpoints.method(SESSION_GET_CONF_REQUEST_WITH_TYPE, SessionForms,
            path='session/{websafeConferenceKey}/{typeOfSession}',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return all sessions of a given conference by type"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # get sessions of this conference, filtered by type
        sessions = Session.query(ancestor=confKey)
        sessions = sessions.filter(Session.typeOfSession == request.typeOfSession.name)

        # return SessionForms
        return self._copySessionsToForms(sessions)

    @endpoints.method(SESSION_GET_SESSION_SPEAKER_REQUEST, SessionForms,
            path='sessionBySpeaker/{speakerName}',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return all sessions given by a speaker, across all conferences"""

        # find websafe key for matching speaker
        speakers = Speaker.query()
        speakers = speakers.filter(Speaker.name == request.speakerName.title())
        if speakers.count() == 0:
            return SessionForms()
        speakerWebsafeUrl = speakers.get().key.urlsafe()

        # query using websafe speaker key, filter with speaker in title case for case-independent query
        sessions = Session.query()
        sessions = sessions.filter(speakerWebsafeUrl == Session.speakerKeys)  #IN filter

        # return SessionForms
        return self._copySessionsToForms(sessions)

    @endpoints.method(SESSION_POST_CONF_REQUEST, SessionForm,
            path='session',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session for a given conference"""

        # get user id + auth check
        user_id = self._getUserId()

        # check for required fields
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")
        if not request.date:
            raise endpoints.BadRequestException("Session 'date' field required")
        if not request.startTime:
            raise endpoints.BadRequestException("Session 'startTime' field required")

        # get the conference key using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # check that user is session creator is also the creator of the conference
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException('Only creator of the conference can add sessions to it')

        # check that speaker keys are valid
        for speakerWebsafeKey in request.speakerKeys:
            speakerKey, speaker = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(speakerWebsafeKey, Speaker)

        # start building a data dictionary
        data = {}
        data['name'] = request.name
        data['highlights'] = request.highlights
        data['speakerKeys'] = request.speakerKeys
        data['duration'] = request.duration
        data['typeOfSession'] = request.typeOfSession.name
        data['date'] = datetime.strptime(request.date[:10], '%Y-%m-%d').date()
        data['startTime'] = datetime.strptime(str(request.startTime)[:4], '%H%M').time()

        # create a custom unique key, with the conference key as ancestor
        s_id = Session.allocate_ids(size=1, parent=confKey)[0]
        s_key = ndb.Key(Session, s_id, parent=confKey)
        data['key'] = s_key

        # write session object to datastore
        session = Session(**data)
        session.put()

        # trigger a task to update featured speaker
        taskqueue.add(
            params={
                'websafeConferenceKey': request.websafeConferenceKey,
                'websafeSpeakerKeys': '&'.join(request.speakerKeys)
            },
            url='/tasks/update_featured_speaker'
        )

        # return SessionForm
        return self._copySessionToForm(session)

    # END OF MY TASK 1 ADDITIONS =================
    # ============================================

    # ============================================
    # MY TASK 2 ADDITIONS ========================

    @endpoints.method(SESSION_POST_WISHLIST_REQUEST, SessionForm,
            path='wishlist',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to user's list of sessions they are interested to attend"""

        # get user id + auth check
        user_id = self._getUserId()

        # get user
        user = ndb.Key(Profile, user_id).get()

        # get session using websafe key (to check that it exists)
        sessionKey, session = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeSessionKey, Session)

        # add session websafe key to wishlist
        if session.key.urlsafe() in user.sessions:
            raise endpoints.ConflictException("Session has already been added to user's wishlist")
        user.sessions.append(session.key.urlsafe())
        user.put()

        # return SessionForm
        return self._copySessionToForm(session)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='wishlist',
            http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return all sessions that a user is interested in"""

        # get user id + auth check
        user_id = self._getUserId()

        # get user
        user = ndb.Key(Profile, user_id).get()

        # return SessionForms
        return self._copySessionsToForms(ndb.get_multi([ConferenceApi._getKeyFromWebsafeKey(sessionWebsafeKey) for sessionWebsafeKey in user.sessions]))

    # END OF MY TASK 2 ADDITIONS =================
    # ============================================

    # ============================================
    # MY TASK 3 ADDITIONS ========================

    @endpoints.method(SESSION_GET_CONF_REQUEST_WITH_DATE, SessionForms,
            path='sessionByDate/{websafeConferenceKey}/{startDate}/{endDate}',
            http_method='GET', name='getConferenceSessionsByDate')
    def getConferenceSessionsByDate(self, request):
        """Return all sessions of a given conference by date range"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # convert date string to python date
        startDate = datetime.strptime(request.startDate[:10], '%Y-%m-%d').date()
        endDate = datetime.strptime(request.endDate[:10], '%Y-%m-%d').date()

        # get sessions of this conference, filtered by date range
        sessions = Session.query(ancestor=confKey)
        sessions = sessions.filter(ndb.AND(Session.date>=startDate, Session.date<=endDate))

        # return SessionForms
        return self._copySessionsToForms(sessions)

    @endpoints.method(SESSION_GET_CONF_REQUEST_WITH_TIME, SessionForms,
            path='sessionByTime/{websafeConferenceKey}/{startTime}/{endTime}',
            http_method='GET', name='getConferenceSessionsByTime')
    def getConferenceSessionsByTime(self, request):
        """Return all sessions of a given conference by daily time range"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # convert time integer to python time
        startTime = datetime.strptime(str(request.startTime)[:4], '%H%M').time()
        endTime = datetime.strptime(str(request.endTime)[:4], '%H%M').time()

        # get sessions of this conference, filtered by time range
        sessions = Session.query(ancestor=confKey)
        sessions = sessions.filter(ndb.AND(Session.startTime>=startTime, Session.startTime<=endTime))

        # return SessionForms
        return self._copySessionsToForms(sessions)

    @endpoints.method(SESSION_GET_CONF_REQUEST_PICKY, SessionForms,
            path='sessionPicky/{websafeConferenceKey}/{antiTypeOfSession}/{latestTime}',
            http_method='GET', name='getConferenceSessionsPicky')
    def getConferenceSessionsPicky(self, request):
        """Return all sessions of a given conference that is not of type antiTypeOfSession and is before lastestTime"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # convert time integer to python time
        latestTime = datetime.strptime(str(request.latestTime)[:4], '%H%M').time()

        # get sessions of this conference, filtered by type
        sessions = Session.query(ancestor=confKey)
        sessions = sessions.filter(Session.typeOfSession != request.antiTypeOfSession.name)

        # filter second equality using Python instead of going through datastore query (because it's not possible at all)
        # this is ok in this application because the number of sessions in a conference will not be too large
        # so using Python (which is slower) to post-process the query results won't be too slow
        sessions = [s for s in sessions if s.startTime <= latestTime]

        # return SessionForms
        return self._copySessionsToForms(sessions)

    # END OF MY TASK 3 ADDITIONS =================
    # ============================================

# - - - Featured Speakers - - - - - - - - - - - - - - - - - - - -

    # ============================================
    # MY TASK 4 ADDITIONS ========================

    @staticmethod
    def _updateFeaturedSpeaker(websafeConferenceKey, websafeSpeakerKeys):
        """Update featured speaker if conditions are met"""

        # get the conference using websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(websafeConferenceKey, Conference)

        # extract keys array from combined string
        websafeSpeakerKeys = websafeSpeakerKeys.split('&')

        # check if speaker has more than 1 session in this conference
        sessions = Session.query(ancestor=confKey)
        counters = {}
        for session in sessions:

            for websafeSpeakerKey in websafeSpeakerKeys:

                # init counter for this key if it does not already exist
                if websafeSpeakerKey not in counters:
                    counters[websafeSpeakerKey] = 0

                # check if this speaker key is in this session's speakers key list
                if websafeSpeakerKey in session.speakerKeys:

                    # increment counter
                    counters[websafeSpeakerKey] += 1

                    # if found more than 1, set memcache to speaker and return (no need to check anymore)
                    if counters[websafeSpeakerKey] > 1:

                        # set memcache
                        memcache.set('%s_featuredSpeaker' % websafeConferenceKey, websafeSpeakerKey)

                        # log that we have found featured speaker for this conference
                        speaker = ndb.Key(urlsafe=websafeSpeakerKey).get()
                        logging.info('Setting featured speaker of conference %s (%s) to %s (%s)' % (websafeConferenceKey, conf.name, websafeSpeakerKey, speaker.name))

                        return

        # log that no featured speaker has been set
        logging.info('No featured speaker set')

    @endpoints.method(SESSION_GET_FEATURED_SPEAKER_REQUEST, SpeakerForm,
            path='speaker/featured/{websafeConferenceKey}',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return featured speaker of a conference from memcache"""

        # check type of websafeConferenceKey
        confKey, conf = ConferenceApi._getKeyAndEntityFromWebsafeKeyOfType(request.websafeConferenceKey, Conference)

        # get featured speaker using key from memcache
        websafeFeaturedSpeakerKey = memcache.get('%s_featuredSpeaker' % request.websafeConferenceKey)
        if websafeFeaturedSpeakerKey:
            featuredSpeaker = ndb.Key(urlsafe=websafeFeaturedSpeakerKey).get()
            return self._copySpeakerToForm(featuredSpeaker)

        # return empty speaker form on failure for no results
        return SpeakerForm()

    # END OF MY TASK 4 ADDITIONS =================
    # ============================================

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


api = endpoints.api_server([ConferenceApi]) # register API
