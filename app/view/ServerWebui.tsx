'use client';
import React, { useState, useEffect, useRef, type ChangeEvent } from 'react';
import { Power, Settings, RefreshCw, Terminal } from 'lucide-react';
import { useTheme } from '~/hooks/useTheme';
import { ThemeMenu } from '../components/ThemeMenu';

interface LogEntry {
  timestamp: string;
  level: string;
  module: string;
  message: string;
}

interface ServerConfig {
  host: string;
  port: number;
  root_dir: string;
  temp_dir: string;
  server_type: 'protocol' | 'threaded' | 'select' | 'async';
  io_mode: 'single' | 'threaded' | 'nonblocking' | 'async';
}

interface ServerStatusResponse {
  running: boolean;
  server_type?: string;
  host?: string;
  port?: number;
  active_connections?: number;
}

const ServerControl: React.FC = () => {
  const { theme, setTheme, currentTheme, mounted } = useTheme();
  const [serverStatus, setServerStatus] = useState<'running' | 'stopped'>(
    'stopped'
  );
  const [activeConnections, setActiveConnections] = useState<number>(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const [config, setConfig] = useState<ServerConfig>({
    host: 'localhost',
    port: 8001,
    root_dir: './server_files/root',
    temp_dir: './server_files/temp',
    server_type: 'protocol',
    io_mode: 'single',
  });

  // 检查服务器状态
  const checkServerStatus = async () => {
    try {
      const response = await fetch('/server/status');
      const data: ServerStatusResponse = await response.json();
      setServerStatus(data.running ? 'running' : 'stopped');
      setActiveConnections(data.active_connections || 0);
    } catch (error) {
      console.error('Failed to check server status:', error);
    }
  };

  // 定期检查服务器状态和获取日志
  useEffect(() => {
    if (!mounted) return;

    const checkStatus = setInterval(checkServerStatus, 5000);

    if (serverStatus === 'running') {
      const fetchLogs = async () => {
        try {
          const response = await fetch('/server/logs');
          const data = await response.json();
          setLogs(data.logs);
          // 自动滚动到日志底部
          logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        } catch (error) {
          console.error('Failed to fetch logs:', error);
        }
      };

      const logsInterval = setInterval(fetchLogs, 2000);
      return () => {
        clearInterval(checkStatus);
        clearInterval(logsInterval);
      };
    }

    return () => clearInterval(checkStatus);
  }, [serverStatus, mounted]);

  // 检查 IO 模式是否可用
  const isIOModeAvailable = (mode: string) => {
    if (config.server_type === 'async') {
      return mode === 'async';
    }
    return mode !== 'async';
  };

  const handleServerControl = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const endpoint =
        serverStatus === 'running' ? '/server/stop' : '/server/start';
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: serverStatus === 'running' ? undefined : JSON.stringify(config),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || '服务器控制失败');
      }

      await checkServerStatus();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('发生未知错误');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfigChange = (
    e: ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setConfig((prev) => {
      const newConfig = {
        ...prev,
        [name]: name === 'port' ? parseInt(value, 10) : value,
      };

      // 当服务器类型改变时，自动调整 IO 模式
      if (name === 'server_type') {
        if (value === 'async') {
          newConfig.io_mode = 'async';
        } else if (prev.io_mode === 'async') {
          newConfig.io_mode = 'single';
        }
      }

      return newConfig;
    });
  };

  if (!mounted) return null;

  return (
    <div
      className={`min-h-screen ${currentTheme.background} ${currentTheme.text}`}
    >
      {/* 头部栏 */}
      <div className={`w-full px-6 py-4 border-b ${currentTheme.border}`}>
        <div className='max-w-7xl mx-auto flex items-center justify-between'>
          <div className='flex items-center gap-4'>
            <h1 className={`text-2xl font-bold ${currentTheme.text}`}>
              文件传输服务器控制面板
            </h1>
          </div>
          <div className='flex items-center gap-4'>
            <div className={`px-4 py-2 rounded-lg ${currentTheme.card}`}>
              活动连接数: {activeConnections}
            </div>
            <ThemeMenu
              theme={theme}
              setTheme={setTheme}
              currentThemeStyle={currentTheme}
            />
          </div>
        </div>
      </div>

      {/* 主内容 */}
      <div className='max-w-7xl mx-auto p-6'>
        <div className='grid grid-cols-12 gap-6'>
          {/* 左侧面板 - 控制与设置 */}
          <div className='col-span-12 lg:col-span-4 space-y-6'>
            {/* 控制面板 */}
            <div
              className={`rounded-lg border shadow-sm p-6 ${currentTheme.card} ${currentTheme.border}`}
            >
              <h2 className={`text-xl font-semibold mb-4 ${currentTheme.text}`}>
                控制面板
              </h2>
              <button
                onClick={handleServerControl}
                disabled={isLoading}
                className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-lg font-medium 
                  ${
                    serverStatus === 'running'
                      ? 'bg-red-500 hover:bg-red-600'
                      : 'bg-green-500 hover:bg-green-600'
                  } 
                  text-white transition-colors`}
              >
                {isLoading ? (
                  <RefreshCw className='animate-spin' size={20} />
                ) : (
                  <Power size={20} />
                )}
                {serverStatus === 'running' ? '停止服务器' : '启动服务器'}
              </button>
              {error && (
                <div className='mt-4 p-4 rounded-lg bg-red-100 border border-red-200 text-red-700'>
                  {error}
                </div>
              )}
            </div>

            {/* 设置面板 */}
            <div
              className={`rounded-lg border shadow-sm p-6 ${currentTheme.card} ${currentTheme.border}`}
            >
              <h2 className={`text-xl font-semibold mb-4 ${currentTheme.text}`}>
                服务器配置
              </h2>
              <div className='space-y-4'>
                <div>
                  <label
                    htmlFor='host'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    主机地址
                  </label>
                  <input
                    id='host'
                    type='text'
                    name='host'
                    value={config.host}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='port'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    端口
                  </label>
                  <input
                    id='port'
                    type='number'
                    name='port'
                    value={config.port}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='root_dir'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    根目录
                  </label>
                  <input
                    id='root_dir'
                    type='text'
                    name='root_dir'
                    value={config.root_dir}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='temp_dir'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    临时目录
                  </label>
                  <input
                    id='temp_dir'
                    type='text'
                    name='temp_dir'
                    value={config.temp_dir}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='server_type'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    服务器类型
                  </label>
                  <select
                    id='server_type'
                    name='server_type'
                    value={config.server_type}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  >
                    <option value='protocol'>Protocol</option>
                    <option value='threaded'>Threaded</option>
                    <option value='select'>Select</option>
                    <option value='async'>Async</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor='io_mode'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    IO 模式
                  </label>
                  <select
                    id='io_mode'
                    name='io_mode'
                    value={config.io_mode}
                    onChange={handleConfigChange}
                    disabled={serverStatus === 'running'}
                    className={`w-full p-2 rounded-lg border ${currentTheme.input}`}
                  >
                    {config.server_type !== 'async' && (
                      <>
                        <option value='single'>Single</option>
                        <option value='threaded'>Threaded</option>
                        <option value='nonblocking'>Non-blocking</option>
                      </>
                    )}
                    {config.server_type === 'async' && (
                      <option value='async'>Async</option>
                    )}
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* 右侧面板 - 日志 */}
          <div className='col-span-12 lg:col-span-8'>
            <div
              className={`rounded-lg border shadow-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              <div className='p-6'>
                <h2
                  className={`text-xl font-semibold mb-4 flex items-center gap-2 ${currentTheme.text}`}
                >
                  <Terminal size={20} />
                  服务器日志
                </h2>
                <div className='bg-gray-900 rounded-lg p-4 h-[calc(100vh-16rem)] overflow-auto font-mono text-sm'>
                  {logs.length === 0 ? (
                    <div className='text-gray-500 text-center mt-4'>
                      暂无日志记录。启动服务器后将显示日志信息。
                    </div>
                  ) : (
                    logs.map((log, index) => (
                      <div key={index} className='py-1'>
                        <span className='text-gray-500'>[{log.timestamp}]</span>{' '}
                        <span
                          className={
                            log.level === 'ERROR'
                              ? 'text-red-400'
                              : log.level === 'WARNING'
                              ? 'text-yellow-400'
                              : 'text-green-400'
                          }
                        >
                          {log.level}
                        </span>{' '}
                        <span className='text-blue-400'>{log.module}:</span>{' '}
                        <span className='text-gray-300'>{log.message}</span>
                      </div>
                    ))
                  )}
                  <div ref={logEndRef} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ServerControl;
