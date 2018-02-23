from __future__ import print_function

import json
import logging

from autobahn.twisted.websocket import WebSocketClientFactory, WebSocketClientProtocol
from twisted.internet.protocol import ReconnectingClientFactory

from . import Message, ServiceResponse
from .event_emitter import EventEmitterMixin

LOGGER = logging.getLogger('roslibpy')


class RosBridgeProtocol(WebSocketClientProtocol):
    """Implements the websocket client protocol to encode/decode JSON ROS Bridge messages."""

    def __init__(self, *args, **kwargs):
        super(RosBridgeProtocol, self).__init__(*args, **kwargs)
        self.factory = None
        self._pending_service_requests = {}
        self._message_handlers = {
            'publish': self._handle_publish,
            'service_response': self._handle_service_response,
            'call_service': self._handle_service_request,
        }
        # TODO: add handlers for op: status

    def send_ros_message(self, message):
        """Encode and serialize ROS Bridge protocol message.

        Args:
            message (:class:`.Message`): ROS Bridge Message to send.
        """
        try:
            json_message = json.dumps(dict(message)).encode('utf8')
            LOGGER.debug('Sending ROS message: %s', json_message)

            self.sendMessage(json_message)
        except StandardError as exception:
            # TODO: Check if it makes sense to raise exception again here
            # Since this is wrapped in many layers of indirection
            LOGGER.exception('Failed to send message, %s', exception)

    def register_message_handlers(self, operation, handler):
        """Register a message handler for a specific operation type.

        Args:
            operation (:obj:`str`): ROS Bridge operation.
            handler: Callback to handle the message.
        """
        if operation in self._message_handlers:
            raise StandardError('Only one handler can be registered per operation')

        self._message_handlers[operation] = handler

    def send_ros_service_request(self, message, callback, errback):
        """Initiate a ROS service request through the ROS Bridge.

        Args:
            message (:class:`.Message`): ROS Bridge Message containing the service request.
            callback: Callback invoked on successful execution.
            errback: Callback invoked on error.
        """
        request_id = message['id']
        self._pending_service_requests[request_id] = (callback, errback)

        json_message = json.dumps(dict(message)).encode('utf8')
        LOGGER.debug('Sending ROS service request: %s', json_message)

        self.sendMessage(json_message)

    def onConnect(self, response):
        LOGGER.debug('Server connected: %s', response.peer)

    def onOpen(self):
        LOGGER.info('Connection to ROS MASTER ready.')
        self.factory.ready(self)

    def onMessage(self, payload, isBinary):
        if isBinary:
            raise NotImplementedError('Add support for binary messages')

        message = Message(json.loads(payload.decode('utf8')))
        handler = self._message_handlers.get(message['op'], None)
        if not handler:
            raise StandardError('No handler registered for operation "%s"' % message['op'])

        handler(message)

    def _handle_publish(self, message):
        self.factory.emit(message['topic'], message['msg'])

    def _handle_service_response(self, message):
        request_id = message['id']
        service_handlers = self._pending_service_requests.get(request_id, None)

        if not service_handlers:
            raise StandardError('No handler registered for service request ID: "%s"' % request_id)

        callback, errback = service_handlers
        del self._pending_service_requests[request_id]

        if 'result' in message and message['result'] is False:
            if errback:
                errback(message['values'])
        else:
            if callback:
                callback(ServiceResponse(message['values']))

    def _handle_service_request(self, message):
        if 'service' not in message:
            raise ValueError('Expected service name missing in service request')

        self.factory.emit(message['service'], message)

    def onClose(self, wasClean, code, reason):
        LOGGER.info('WebSocket connection closed: %s', reason)


class RosBridgeClientFactory(EventEmitterMixin, ReconnectingClientFactory, WebSocketClientFactory):
    """Factory to construct instance of the ROS Bridge protocol."""
    protocol = RosBridgeProtocol

    def __init__(self, *args, **kwargs):
        super(RosBridgeClientFactory, self).__init__(*args, **kwargs)
        self._proto = None
        self.setProtocolOptions(closeHandshakeTimeout=5)

    def on_ready(self, callback):
        if self._proto:
            callback(self._proto)
        else:
            self.once('ready', callback)

    def ready(self, proto):
        self._proto = proto
        self.emit('ready', proto)

    def startedConnecting(self, connector):
        LOGGER.debug('Started to connect...')

    def clientConnectionLost(self, connector, reason):
        LOGGER.debug('Lost connection. Reason: %s', reason)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        self._proto = None

    def clientConnectionFailed(self, connector, reason):
        LOGGER.debug('Connection failed. Reason: %s', reason)
        ReconnectingClientFactory.clientConnectionFailed(
            self, connector, reason)
        self._proto = None