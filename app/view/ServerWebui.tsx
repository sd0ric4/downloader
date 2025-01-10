'use client';
import React, { useState, useEffect, useRef, type ChangeEvent } from 'react';
import { Power, Settings, RefreshCw, Terminal, Moon, Sun } from 'lucide-react';
import { useTheme } from '~/hooks/useTheme';
import { ThemeMenu } from '../components/ThemeMenu';

interface LogEntry {
  timestamp: string;
  level: 'ERROR' | 'WARNING' | 'INFO';
  module: string;
  message: string;
}

interface ServerConfig {
  host: string;
  port: number;
  root_dir: string;
  temp_dir: string;
  server_type: 'protocol' | 'threaded' | 'select' | 'async';
  io_mode: 'single' | 'threaded' | 'nonblocking';
}

const ServerControl: React.FC = () => {
  const { theme, setTheme, currentTheme, mounted } = useTheme();
  const [serverStatus, setServerStatus] = useState<'running' | 'stopped'>(
    'stopped'
  );
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

  useEffect(() => {
    if (!mounted) return;

    if (serverStatus === 'running') {
      const fetchLogs = async () => {
        try {
          const response = await fetch('/api/server/logs');
          const data = await response.json();
          setLogs(data.logs);
        } catch (error) {
          console.error('Failed to fetch logs:', error);
        }
      };

      const interval = setInterval(fetchLogs, 2000);
      return () => clearInterval(interval);
    }
  }, [serverStatus, mounted]);

  const handleConfigChange = (
    e: ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setConfig((prev) => ({
      ...prev,
      [name]: name === 'port' ? parseInt(value, 10) : value,
    }));
  };

  const handleServerControl = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/server/control', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          action: serverStatus === 'running' ? 'stop' : 'start',
          config,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to control server');
      }

      setServerStatus(serverStatus === 'running' ? 'stopped' : 'running');
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

  if (!mounted) return null;

  return (
    <div
      className={`min-h-screen ${currentTheme.background} ${currentTheme.text} transition-colors duration-300`}
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
                aria-label={
                  serverStatus === 'running' ? '停止服务器' : '启动服务器'
                }
                className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-lg font-medium hover:scale-105 transition-transform ${currentTheme.activeButton} ${currentTheme.border}`}
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
                    placeholder='输入主机地址'
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
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
                    placeholder='输入端口号'
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='rootDir'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    根目录
                  </label>
                  <input
                    id='rootDir'
                    type='text'
                    name='rootDir'
                    value={config.root_dir}
                    onChange={handleConfigChange}
                    placeholder='输入根目录路径'
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='tempDir'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    临时目录
                  </label>
                  <input
                    id='tempDir'
                    type='text'
                    name='tempDir'
                    value={config.temp_dir}
                    onChange={handleConfigChange}
                    placeholder='输入临时目录路径'
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
                  />
                </div>

                <div>
                  <label
                    htmlFor='serverType'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    服务器类型
                  </label>
                  <select
                    id='serverType'
                    name='serverType'
                    value={config.server_type}
                    onChange={handleConfigChange}
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
                  >
                    <option value='protocol'>Protocol</option>
                    <option value='threaded'>Threaded</option>
                    <option value='select'>Select</option>
                    <option value='async'>Async</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor='ioMode'
                    className={`block text-sm font-medium mb-1 ${currentTheme.subtext}`}
                  >
                    IO 模式
                  </label>
                  <select
                    id='ioMode'
                    name='ioMode'
                    value={config.io_mode}
                    onChange={handleConfigChange}
                    className={`w-full p-2 rounded-lg border focus:ring-2 focus:ring-blue-500 ${currentTheme.input}`}
                  >
                    <option value='single'>Single</option>
                    <option value='threaded'>Threaded</option>
                    <option value='nonblocking'>Non-blocking</option>
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
                          className={`${
                            log.level === 'ERROR'
                              ? 'text-red-400'
                              : log.level === 'WARNING'
                              ? 'text-yellow-400'
                              : 'text-green-400'
                          }`}
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
