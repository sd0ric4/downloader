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

const mockFiles = [
  {
    name: '测试文件.txt',
    size: 1138522,
    is_directory: false,
    modified_time: 1736522270,
  },
  {
    name: '示例文件夹',
    size: 0,
    is_directory: true,
    modified_time: 1736505741,
  },
  {
    name: '大文件.zip',
    size: 1073741824,
    is_directory: false,
    modified_time: 1736522270,
  },
];

const FileListPreview = () => {
  const { theme, setTheme, currentTheme, mounted } = useTheme();
  const formatFileSize = (size: number) => {
    if (size < 1024) return `${size}B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)}KB`;
    if (size < 1024 * 1024 * 1024)
      return `${(size / 1024 / 1024).toFixed(2)}MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(2)}GB`;
  };

  const formatDate = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleString();
  };
  if (!mounted) return null;
  return (
    <div className={`min-h-screen ${currentTheme.background}`}>
      <div className='max-w-7xl mx-auto py-10 px-4 sm:px-6 lg:px-8'>
        {/* 头部区域 */}
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

        {/* 搜索和操作区 */}
        <div className='mb-6 flex flex-col sm:flex-row gap-4'>
          <div className='relative flex-1'>
            <div className='absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none'>
              <Search className={`w-5 h-5 ${currentTheme.subtext}`} />
            </div>
            <input
              type='text'
              placeholder='搜索文件...'
              className={`block w-full pl-10 pr-4 py-2.5 rounded-xl border shadow-sm
              focus:outline-none focus:ring-2 focus:ring-opacity-50 focus:ring-blue-500
              ${currentTheme.input} backdrop-blur-sm`}
            />
          </div>
          <button
            className={`inline-flex items-center justify-center px-4 py-2.5 rounded-xl
            ${currentTheme.activeButton} shadow-sm hover:shadow gap-2 whitespace-nowrap
            active:transform active:scale-95 transition-all duration-200`}
          >
            <RefreshCw className='w-5 h-5' />
            刷新列表
          </button>
        </div>

        {/* 文件列表 */}
        <div
          className={`${currentTheme.card} backdrop-blur-sm rounded-2xl shadow-xl border ${currentTheme.border} overflow-hidden`}
        >
          <div className='divide-y divide-gray-100/20'>
            {mockFiles.map((file) => (
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
                    className={`ml-4 flex items-center px-4 py-2 text-sm rounded-lg gap-2
                    ${currentTheme.button} group-hover:shadow-sm transition-all duration-200`}
                  >
                    <Download className='w-5 h-5' />
                    <span className='hidden sm:inline'>下载</span>
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* 底部统计信息 */}
        <div className='mt-6 flex items-center justify-between'>
          <div
            className={`text-sm ${currentTheme.subtext} flex items-center gap-2`}
          >
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              共 {mockFiles.length} 个项目
            </span>
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              {mockFiles.filter((f) => f.is_directory).length} 个文件夹
            </span>
            <span
              className={`px-3 py-1 rounded-full shadow-sm border 
              backdrop-blur-sm ${currentTheme.card} ${currentTheme.border}`}
            >
              {mockFiles.filter((f) => !f.is_directory).length} 个文件
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FileListPreview;
