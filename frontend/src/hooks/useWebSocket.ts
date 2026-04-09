import { useState, useEffect, useCallback, useRef } from 'react';

export type WSMessage = {
  type: 'TICK' | 'WHALE_ALERT' | 'DQ_ALERT' | 'SYSTEM';
  data: any;
};

const BASE_RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 60000;

export function useWebSocket(url: string = `ws://${window.location.host}/ws`) {
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [reconnectCount, setReconnectCount] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef<number>(BASE_RECONNECT_DELAY_MS);
  const pingIntervalRef = useRef<number | null>(null);
  const pingSentAtRef = useRef<number | null>(null);

  const clearTimers = () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  };

  const connect = useCallback(() => {
    // Avoid double connection
    if (socketRef.current?.readyState === WebSocket.OPEN) return;

    console.log(`🔌 Connecting to WebSocket... (attempt ${reconnectDelayRef.current / 1000}s delay used)`);
    setStatus('connecting');

    const socket = new WebSocket(url);

    socket.onopen = () => {
      console.log('✅ WebSocket Connected');
      setStatus('open');
      // Reset backoff on successful connection
      reconnectDelayRef.current = BASE_RECONNECT_DELAY_MS;
      setReconnectCount(0);

      // Start latency ping every 10 seconds
      pingIntervalRef.current = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          pingSentAtRef.current = Date.now();
          socket.send(JSON.stringify({ type: 'PING' }));
        }
      }, 10000);
    };

    socket.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        // Handle pong for latency tracking
        if ((msg as any).type === 'PONG' && pingSentAtRef.current) {
          setLatency(Date.now() - pingSentAtRef.current);
          pingSentAtRef.current = null;
          return;
        }
        setLastMessage(msg);
      } catch (err) {
        console.error('❌ WS Message Parse Error:', err);
      }
    };

    socket.onclose = () => {
      console.warn(`⚠️ WebSocket Disconnected. Reconnecting in ${reconnectDelayRef.current / 1000}s...`);
      setStatus('closed');
      clearTimers();

      // Exponential backoff: 3s → 6s → 12s → 24s → ... max 60s
      const delay = reconnectDelayRef.current;
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectDelayRef.current = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
        setReconnectCount(c => c + 1);
        connect();
      }, delay);
    };

    socket.onerror = (err) => {
      console.error('❌ WebSocket Error:', err);
      socket.close();
    };

    socketRef.current = socket;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      clearTimers();
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((msg: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return {
    status,
    lastMessage,
    sendMessage,
    latency,
    reconnectCount,
    isConnected: status === 'open',
  };
}
