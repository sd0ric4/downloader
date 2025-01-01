import React from 'react';

interface HeaderFieldProps {
  name: string;
  size: string;
  color: string;
}

interface MessageTypeProps {
  type: string;
  id: string;
  description: string;
}

const HeaderField = ({ name, size, color }: HeaderFieldProps) => (
  <div
    className={`${color} rounded-xl p-4 flex flex-col items-center justify-center flex-1`}
  >
    <div className='font-bold text-base mb-1'>{name}</div>
    <div className='text-gray-600 text-sm'>{size}</div>
  </div>
);

const MessageType = ({ type, id, description }: MessageTypeProps) => (
  <div className='p-4 bg-gray-50 rounded-lg mb-3 last:mb-0'>
    <div className='font-bold mb-1'>
      {type} ({id})
    </div>
    <div className='text-sm text-gray-600'>{description}</div>
  </div>
);

const ProtocolStructure = () => {
  return (
    <div className='p-8 max-w-6xl mx-auto'>
      <h2 className='text-2xl font-bold mb-8'>
        DBP (Download Block Protocol) 协议帧结构
      </h2>

      {/* 协议帧结构 */}
      <div className='mb-12'>
        <div className='shadow-lg rounded-3xl p-6 border-2 border-gray-200'>
          {/* 头部字段 */}
          <div className='flex gap-2 mb-4'>
            <HeaderField name='Version' size='2 bytes' color='bg-orange-50' />
            <HeaderField name='Msg Type' size='2 bytes' color='bg-green-50' />
            <HeaderField
              name='Payload Length'
              size='4 bytes'
              color='bg-blue-50'
            />
            <HeaderField
              name='Sequence Number'
              size='4 bytes'
              color='bg-pink-50'
            />
            <HeaderField
              name='Chunk Number'
              size='4 bytes'
              color='bg-purple-50'
            />
            <HeaderField
              name='MD5 Checksum'
              size='32 bytes'
              color='bg-orange-50/50'
            />
          </div>

          {/* 负载数据 */}
          <div className='bg-gray-50 p-6 rounded-xl text-center font-medium'>
            Variable Length Payload Data
          </div>
        </div>
      </div>

      {/* 消息类型说明 */}
      <div className='mb-12'>
        <h3 className='text-xl font-bold mb-4'>消息类型</h3>
        <div className='bg-white rounded-lg border border-gray-200 p-4'>
          <MessageType
            type='HANDSHAKE'
            id='1'
            description='初始连接握手，包含协议版本和客户端ID'
          />
          <MessageType
            type='FILE_REQUEST'
            id='2'
            description='请求下载文件，包含文件名和路径'
          />
          <MessageType
            type='FILE_METADATA'
            id='3'
            description='文件元数据，包含文件大小、总块数、校验和等信息'
          />
          <MessageType
            type='FILE_DATA'
            id='4'
            description='文件数据块，包含块的实际内容'
          />
          <MessageType
            type='CHECKSUM_VERIFY'
            id='5'
            description='数据块校验和验证'
          />
          <MessageType
            type='ERROR'
            id='6'
            description='错误信息，包含错误码和描述'
          />
          <MessageType type='ACK' id='7' description='数据块接收确认' />
          <MessageType
            type='RESUME_REQUEST'
            id='8'
            description='断点续传请求，指定续传的起始块号'
          />
        </div>
      </div>

      {/* 协议特点说明 */}
      <div>
        <h3 className='text-xl font-bold mb-4'>协议特点说明</h3>
        <div className='space-y-4'>
          <div className='bg-blue-50 p-4 rounded-lg'>
            <h4 className='font-bold mb-2'>封帧格式</h4>
            <ul className='list-disc list-inside text-sm space-y-1'>
              <li>固定大小的头部(48字节)保证解析效率</li>
              <li>变长数据段支持不同大小的数据块</li>
              <li>MD5校验保证数据完整性</li>
              <li>序列号和块号实现可靠传输</li>
            </ul>
          </div>

          <div className='bg-green-50 p-4 rounded-lg'>
            <h4 className='font-bold mb-2'>可靠性保证</h4>
            <ul className='list-disc list-inside text-sm space-y-1'>
              <li>序列号机制确保数据有序性</li>
              <li>块级别的ACK确认机制</li>
              <li>MD5校验保证数据准确性</li>
              <li>支持数据块重传</li>
            </ul>
          </div>

          <div className='bg-purple-50 p-4 rounded-lg'>
            <h4 className='font-bold mb-2'>扩展性</h4>
            <ul className='list-disc list-inside text-sm space-y-1'>
              <li>版本号(2字节)支持协议升级</li>
              <li>消息类型(2字节)预留扩展空间</li>
              <li>4字节长度字段支持大文件传输</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProtocolStructure;
