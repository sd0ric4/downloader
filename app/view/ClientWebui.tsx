import React, { useState, useEffect } from 'react';
import {
  Calendar,
  Download,
  Folder,
  File,
  RefreshCw,
  Search,
  Info,
} from 'lucide-react';
import ThemeMenu from '~/components/ThemeMenu';
import { useTheme } from '~/hooks/useTheme';

// 定义文件类型接口
interface FileItem {
  name: string;
  size: number;
  is_directory: boolean;
  modified_time: number;
}

// 定义下载进度类型
interface DownloadProgress {
  [key: string]: number;
}
interface DownloadStatus {
  remote_filename: string;
  local_filename: string;
  status: 'pending' | 'downloading' | 'completed' | 'failed';
  progress: number;
  error: string | null;
}

interface DownloadStatuses {
  [key: string]: DownloadStatus;
}
const FileListManager: React.FC = () => {
  const { theme, setTheme, currentTheme, mounted } = useTheme();
  const [files, setFiles] = useState<FileItem[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [downloadProgress, setDownloadProgress] = useState<DownloadProgress>(
    {}
  );
  const [downloadStatuses, setDownloadStatuses] = useState<DownloadStatuses>(
    {}
  );
  // 获取文件列表
  const fetchFiles = async (): Promise<void> => {
    try {
      setLoading(true);
      const response = await fetch('http://localhost:8013/files');
      const data = await response.json();
      setFiles(data.files);
    } catch (error) {
      console.error('Error fetching files:', error);
    } finally {
      setLoading(false);
    }
  };

  // 下载文件
  const downloadFile = async (filename: string): Promise<void> => {
    try {
      const response = await fetch('http://localhost:8013/download', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          remote_filename: filename,
          local_filename: `./test_files/root/${filename}`,
        }),
      });

      if (!response.ok) {
        throw new Error('Download failed');
      }

      // 开始轮询下载进度
      startProgressPolling(filename);
    } catch (error) {
      console.error('Error downloading file:', error);
    }
  };

  // 轮询下载进度
  const startProgressPolling = (filename: string): void => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(
          `http://localhost:8013/download/progress/${filename}`
        );
        const status: DownloadStatus = await response.json();

        setDownloadStatuses((prev) => ({
          ...prev,
          [filename]: status,
        }));

        // 如果下载完成或失败,停止轮询
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(pollInterval);
        }
      } catch (error) {
        console.error('Error fetching status:', error);
        clearInterval(pollInterval);
      }
    }, 1000);
  };
  useEffect(() => {
    fetchFiles();
  }, []);

  const formatFileSize = (size: number): string => {
    if (size < 1024) return `${size}B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)}KB`;
    if (size < 1024 * 1024 * 1024)
      return `${(size / 1024 / 1024).toFixed(2)}MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(2)}GB`;
  };

  const formatDate = (timestamp: number): string => {
    return new Date(timestamp * 1000).toLocaleString();
  };

  const filteredFiles = files.filter((file) =>
    file.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const getDownloadButtonContent = (filename: string) => {
    const status = downloadStatuses[filename];

    if (!status) {
      return (
        <>
          <Download className='w-5 h-5' />
          <span className='hidden sm:inline'>下载</span>
        </>
      );
    }

    switch (status.status) {
      case 'pending':
        return (
          <>
            <RefreshCw className='w-5 h-5 animate-spin' />
            <span className='hidden sm:inline'>等待中</span>
          </>
        );
      case 'downloading':
        return (
          <>
            <Download className='w-5 h-5 animate-pulse' />
            <span className='hidden sm:inline'>
              {(status.progress * 100).toFixed(1)}%
            </span>
          </>
        );
      case 'completed':
        return (
          <>
            <Download className='w-5 h-5 text-green-500' />
            <span className='hidden sm:inline text-green-500'>已完成</span>
          </>
        );
      case 'failed':
        return (
          <>
            <Download className='w-5 h-5 text-red-500' />
            <span className='hidden sm:inline text-red-500'>失败</span>
          </>
        );
    }
  };

  if (!mounted) return null;

  return (
    <div className={`min-h-screen ${currentTheme.background}`}>
      <div className='max-w-7xl mx-auto py-10 px-4 sm:px-6 lg:px-8'>
        {/* Header */}
        <div className='mb-8 flex justify-between items-start'>
          <div>
            <h1 className={`text-2xl font-semibold mb-2 ${currentTheme.text}`}>
              文件管理器
            </h1>
            <p
              className={`text-sm flex items-center gap-1 ${currentTheme.subtext}`}
            >
              <Info className='w-4 h-4' />
              选择文件进行下载或管理
            </p>
          </div>
          <ThemeMenu
            theme={theme}
            setTheme={setTheme}
            currentThemeStyle={currentTheme}
          />
        </div>

        {/* Search and Actions */}
        <div className='mb-6 flex flex-col sm:flex-row gap-4'>
          <div className='relative flex-1'>
            <div className='absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none'>
              <Search className={`w-5 h-5 ${currentTheme.subtext}`} />
            </div>
            <input
              type='text'
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder='搜索文件...'
              className={`block w-full pl-10 pr-4 py-2.5 rounded-xl border shadow-sm
              focus:outline-none focus:ring-2 focus:ring-opacity-50 focus:ring-blue-500
              ${currentTheme.input} backdrop-blur-sm`}
            />
          </div>
          <button
            onClick={fetchFiles}
            disabled={loading}
            className={`inline-flex items-center justify-center px-4 py-2.5 rounded-xl
            ${
              currentTheme.activeButton
            } shadow-sm hover:shadow gap-2 whitespace-nowrap
            active:transform active:scale-95 transition-all duration-200
            ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            刷新列表
          </button>
        </div>

        {/* File List */}
        <div
          className={`${currentTheme.card} backdrop-blur-sm rounded-2xl shadow-xl border ${currentTheme.border} overflow-hidden`}
        >
          <div className='divide-y divide-gray-100/20'>
            {filteredFiles.map((file) => (
              <div
                key={file.name}
                className={`group relative flex items-center justify-between px-6 py-4 
                  ${currentTheme.hover} transition-all duration-300`}
              >
                <div
                  className='absolute inset-y-0 left-0 w-1 bg-blue-500 scale-y-0 group-hover:scale-y-100 
                  transition-transform duration-200'
                />
                <div className='flex items-center space-x-4 flex-1 min-w-0'>
                  <div
                    className={`p-3 rounded-xl ${
                      file.is_directory
                        ? 'bg-gradient-to-br from-amber-100/80 to-amber-50/80'
                        : 'bg-gradient-to-br from-blue-100/80 to-blue-50/80'
                    } group-hover:shadow-md transition-shadow duration-300 backdrop-blur-sm`}
                  >
                    {file.is_directory ? (
                      <Folder className='w-6 h-6 text-amber-600' />
                    ) : (
                      <File className='w-6 h-6 text-blue-600' />
                    )}
                  </div>
                  <div className='flex flex-col flex-1 min-w-0'>
                    <span
                      className={`text-base font-medium truncate group-hover:text-blue-500 
                      transition-colors duration-200 ${currentTheme.text}`}
                    >
                      {file.name}
                    </span>
                    <div className='flex items-center space-x-4 mt-1'>
                      <span className={currentTheme.subtext}>
                        {formatFileSize(file.size)}
                      </span>
                      <div
                        className={`flex items-center ${currentTheme.subtext}`}
                      >
                        <Calendar className='w-4 h-4 mr-1.5' />
                        {formatDate(file.modified_time)}
                      </div>
                    </div>
                  </div>
                </div>

                {!file.is_directory && (
                  <button
                    onClick={() => downloadFile(file.name)}
                    disabled={
                      downloadStatuses[file.name]?.status === 'downloading'
                    }
                    className={`ml-4 flex items-center px-4 py-2 text-sm rounded-lg gap-2
    ${currentTheme.button} group-hover:shadow-sm transition-all duration-200
    ${
      downloadStatuses[file.name]?.status === 'downloading'
        ? 'opacity-50 cursor-not-allowed'
        : ''
    }`}
                  >
                    {getDownloadButtonContent(file.name)}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Stats */}
        <div className='mt-6 flex items-center justify-between'>
          <div
            className={`text-sm ${currentTheme.subtext} flex items-center gap-2`}
          >
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              共 {filteredFiles.length} 个项目
            </span>
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              {filteredFiles.filter((f) => f.is_directory).length} 个文件夹
            </span>
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              {filteredFiles.filter((f) => !f.is_directory).length} 个文件
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FileListManager;
