import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '~/components/ui/card';
import {
  ArrowRight,
  ArrowLeft,
  Server,
  Laptop,
  AlertTriangle,
  Play,
  RefreshCw,
  CheckCircle,
  FastForward,
} from 'lucide-react';

// Define types for the protocol messages and flow data
interface ProtocolHeader {
  version: number;
  msg_type: string;
  sequence_number: number;
  chunk_number: number;
  payload_length: number;
  checksum: string;
}

interface MessagePayload {
  [key: string]: any;
}

interface ProtocolMessage {
  step: string;
  direction: 'left' | 'right';
  type: string;
  title: string;
  message: string;
  header: ProtocolHeader;
  payload?: MessagePayload;
  isChunk?: boolean;
  totalChunks?: number;
  startChunk?: number;
  chunkSize?: number;
  error?: boolean;
}

interface FlowData {
  title: string;
  messages: ProtocolMessage[];
}

interface FlowDataMap {
  [key: string]: FlowData;
}
const normalizeTotalChunks = (message: ProtocolMessage): number => {
  return message.isChunk && message.totalChunks ? message.totalChunks : 1;
};
const getTotalChunks = (message: ProtocolMessage | undefined): number => {
  if (!message) return 1;
  return message.totalChunks ?? 1;
};
const INITIAL_FLOW_DATA: FlowDataMap = {
  normal: {
    title: 'Normal Download Flow',
    messages: [
      {
        step: 'handshake',
        direction: 'right',
        type: 'HANDSHAKE',
        title: 'Initial Handshake',
        message:
          'Client initiates connection with protocol version and unique ID',
        header: {
          version: 1,
          msg_type: 'HANDSHAKE',
          sequence_number: 0,
          chunk_number: 0,
          payload_length: 64,
          checksum: 'e2fc714c4727ee9395f324cd2e7f331f',
        },
        payload: {
          version: 1,
          client_id: 'c8b7e1a2d3f4',
        },
      },
      {
        step: 'handshake_ack',
        direction: 'left',
        type: 'ACK',
        title: 'Handshake Acknowledgment',
        message: 'Server acknowledges handshake',
        header: {
          version: 1,
          msg_type: 'ACK',
          sequence_number: 1,
          chunk_number: 0,
          payload_length: 0,
          checksum: 'd41d8cd98f00b204e9800998ecf8427e',
        },
      },
      {
        step: 'file_request',
        direction: 'right',
        type: 'FILE_REQUEST',
        title: 'File Request',
        message: 'Client requests specific file for download',
        header: {
          version: 1,
          msg_type: 'FILE_REQUEST',
          sequence_number: 2,
          chunk_number: 0,
          payload_length: 32,
          checksum: 'f4eff6c89c4c079f',
        },
        payload: {
          filename: 'example.txt',
        },
      },
      {
        step: 'file_metadata',
        direction: 'left',
        type: 'FILE_METADATA',
        title: 'File Metadata Response',
        message:
          'Server sends file metadata including size, chunks, and checksums',
        header: {
          version: 1,
          msg_type: 'FILE_METADATA',
          sequence_number: 3,
          chunk_number: 0,
          payload_length: 128,
          checksum: 'a8c87f98b1c9f38b',
        },
        payload: {
          file_size: 1048576, // 1MB
          total_chunks: 128,
          chunk_size: 8192, // 8KB chunks
          file_checksum: 'complete_file_md5_hash',
        },
      },
      {
        step: 'data_transfer',
        direction: 'left',
        type: 'FILE_DATA',
        title: 'File Data Transfer',
        message: 'Server sends file data in chunks',
        header: {
          version: 1,
          msg_type: 'FILE_DATA',
          sequence_number: 4,
          chunk_number: 1,
          payload_length: 8192,
          checksum: 'chunk_md5_hash',
        },
        isChunk: true,
        totalChunks: 128,
        chunkSize: 8192,
      },
      {
        step: 'chunk_ack',
        direction: 'right',
        type: 'ACK',
        title: 'Chunk Acknowledgment',
        message: 'Client confirms chunk receipt',
        header: {
          version: 1,
          msg_type: 'ACK',
          sequence_number: 5,
          chunk_number: 1,
          payload_length: 0,
          checksum: 'd41d8cd98f00b204e9800998ecf8427e',
        },
        isChunk: true,
      },
    ],
  },
  resume: {
    title: 'Resume Download Flow',
    messages: [
      {
        step: 'resume_handshake',
        direction: 'right',
        type: 'HANDSHAKE',
        title: 'Resume Connection',
        message: 'Client initiates new connection for resume',
        header: {
          version: 1,
          msg_type: 'HANDSHAKE',
          sequence_number: 0,
          chunk_number: 64,
          payload_length: 64,
          checksum: 'e2fc714c4727ee9395f324cd2e7f331f',
        },
        payload: {
          version: 1,
          client_id: 'c8b7e1a2d3f4',
        },
      },
      {
        step: 'resume_request',
        direction: 'right',
        type: 'RESUME_REQUEST',
        title: 'Resume Request',
        message: 'Client requests to resume from last successful chunk',
        header: {
          version: 1,
          msg_type: 'RESUME_REQUEST',
          sequence_number: 1,
          chunk_number: 64,
          payload_length: 96,
          checksum: 'resume_request_md5',
        },
        payload: {
          filename: 'example.txt',
          start_chunk: 64,
        },
      },
      {
        step: 'resume_metadata',
        direction: 'left',
        type: 'FILE_METADATA',
        title: 'Resume Metadata',
        message: 'Server confirms remaining file portions',
        header: {
          version: 1,
          msg_type: 'FILE_METADATA',
          sequence_number: 2,
          chunk_number: 64,
          payload_length: 128,
          checksum: 'metadata_checksum',
        },
        payload: {
          remaining_size: 524288,
          remaining_chunks: 64,
          chunk_size: 8192,
          file_checksum: 'complete_file_md5_hash',
        },
      },
      {
        step: 'resume_transfer',
        direction: 'left',
        type: 'FILE_DATA',
        title: 'Resumed Data Transfer',
        message: 'Server continues file transfer from checkpoint',
        header: {
          version: 1,
          msg_type: 'FILE_DATA',
          sequence_number: 3,
          chunk_number: 64,
          payload_length: 8192,
          checksum: 'chunk_64_md5_hash',
        },
        isChunk: true,
        totalChunks: 64,
        startChunk: 64,
      },
    ],
  },
  error: {
    title: 'Error Handling Flow',
    messages: [
      {
        step: 'corrupt_data',
        direction: 'left',
        type: 'FILE_DATA',
        title: 'Corrupted Data Transfer',
        message: 'Server sends file chunk that becomes corrupted',
        header: {
          version: 1,
          msg_type: 'FILE_DATA',
          sequence_number: 10,
          chunk_number: 5,
          payload_length: 8192,
          checksum: 'original_checksum',
        },
      },
      {
        step: 'checksum_error',
        direction: 'right',
        type: 'ERROR',
        title: 'Checksum Error',
        message: 'Client detects checksum mismatch',
        error: true,
        header: {
          version: 1,
          msg_type: 'ERROR',
          sequence_number: 11,
          chunk_number: 5,
          payload_length: 64,
          checksum: 'error_checksum',
        },
        payload: {
          error_type: 'CHECKSUM_ERROR',
          chunk_number: 5,
          expected: 'original_checksum',
          received: 'corrupted_checksum',
        },
      },
      {
        step: 'retry_chunk',
        direction: 'left',
        type: 'FILE_DATA',
        title: 'Chunk Retry',
        message: 'Server retransmits the corrupted chunk',
        header: {
          version: 1,
          msg_type: 'FILE_DATA',
          sequence_number: 12,
          chunk_number: 5,
          payload_length: 8192,
          checksum: 'original_checksum',
        },
      },
      {
        step: 'retry_success',
        direction: 'right',
        type: 'ACK',
        title: 'Retry Success',
        message: 'Client confirms successful chunk retry',
        header: {
          version: 1,
          msg_type: 'ACK',
          sequence_number: 13,
          chunk_number: 5,
          payload_length: 0,
          checksum: 'd41d8cd98f00b204e9800998ecf8427e',
        },
      },
    ],
  },
};
interface ProtocolHeaderProps {
  header: ProtocolHeader;
}
const ProtocolHeader: React.FC<ProtocolHeaderProps> = ({ header }) => (
  <div className='bg-gray-50 p-4 rounded-lg border border-gray-200'>
    <h3 className='text-sm font-semibold text-gray-700 mb-2'>
      Protocol Header
    </h3>
    <div className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>
      <div>Version: {header.version}</div>
      <div>Type: {header.msg_type}</div>
      <div>Sequence: {header.sequence_number}</div>
      <div>Chunk: {header.chunk_number}</div>
      <div className='col-span-2'>Payload Length: {header.payload_length}</div>
      <div className='col-span-2 text-xs break-all'>
        Checksum: {header.checksum}
      </div>
    </div>
  </div>
);
interface ChunkProgressProps {
  current: number;
  total: number;
  isActive: boolean;
}
const ChunkProgress: React.FC<ChunkProgressProps> = ({
  current,
  total,
  isActive,
}) => (
  <div className='w-full space-y-2'>
    <div className='flex justify-between text-sm text-gray-500'>
      <span>Transfer Progress</span>
      <span>{Math.round((current / total) * 100)}%</span>
    </div>
    <div className='h-2 w-full bg-gray-100 rounded-full overflow-hidden'>
      <div
        className='h-full bg-blue-500 transition-all duration-500 ease-linear rounded-full'
        style={{
          width: `${(current / total) * 100}%`,
          opacity: isActive ? '1' : '0.5',
        }}
      />
    </div>
    <div className='text-xs text-gray-500 text-right'>
      Chunk {current} of {total}
    </div>
  </div>
);
interface MessageInfoProps {
  message: ProtocolMessage;
  active: boolean;
  chunkNum: number;
}

const MessageInfo: React.FC<MessageInfoProps> = ({
  message,
  active,
  chunkNum,
}) => {
  const isTransfer = message.type === 'FILE_DATA' && message.isChunk;

  return (
    <div
      className={`transform transition-all duration-500 ${
        active ? 'scale-100 opacity-100' : 'scale-95 opacity-50'
      }`}
    >
      <div className='flex items-center gap-4 mb-4'>
        <div className='flex items-center gap-2'>
          {message.direction === 'right' ? (
            <>
              <Laptop className='w-8 h-8 text-blue-600' />
              <ArrowRight className='w-6 h-6' />
              <Server className='w-8 h-8 text-green-600' />
            </>
          ) : (
            <>
              <Server className='w-8 h-8 text-green-600' />
              <ArrowLeft className='w-6 h-6' />
              <Laptop className='w-8 h-8 text-blue-600' />
            </>
          )}
        </div>
        <div
          className={`px-3 py-1 rounded-full text-sm font-medium ${
            message.error
              ? 'bg-red-100 text-red-700'
              : 'bg-blue-100 text-blue-700'
          }`}
        >
          {message.type}
        </div>
      </div>

      <div className='grid grid-cols-2 gap-6 ml-16'>
        <div className='space-y-4'>
          <h2 className='text-lg font-semibold'>{message.title}</h2>
          <p className='text-gray-600'>{message.message}</p>
          {message.error && (
            <div className='flex items-center gap-2 text-red-600'>
              <AlertTriangle className='w-5 h-5' />
              <span>Error detected in transmission</span>
            </div>
          )}
          {message.payload && (
            <div className='bg-gray-50 p-4 rounded-lg border border-gray-200'>
              <h3 className='text-sm font-semibold mb-2'>Payload Data</h3>
              <pre className='text-xs overflow-auto whitespace-pre-wrap'>
                {JSON.stringify(message.payload, null, 2)}
              </pre>
            </div>
          )}
          {isTransfer && (
            <ChunkProgress
              current={chunkNum}
              total={message.totalChunks || 1}
              isActive={active}
            />
          )}
        </div>
        <ProtocolHeader
          header={
            message.isChunk
              ? {
                  ...message.header,
                  chunk_number: message.startChunk
                    ? chunkNum + message.startChunk
                    : chunkNum,
                  sequence_number:
                    message.header.sequence_number + chunkNum - 1,
                }
              : message.header
          }
        />
      </div>
    </div>
  );
};

// Update the component with fixed type handling
const ProtocolVisualization: React.FC = () => {
  const [currentFlow, setCurrentFlow] = useState<keyof FlowDataMap>('normal');
  const [currentStep, setCurrentStep] = useState(0);
  const [chunkNum, setChunkNum] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [autoSkipChunks, setAutoSkipChunks] = useState(true);

  const messages = INITIAL_FLOW_DATA[currentFlow]?.messages || [];
  const currentMessage = messages[currentStep] || messages[0];
  const totalChunks = getTotalChunks(currentMessage);

  useEffect(() => {
    let timer: NodeJS.Timeout | undefined;
    if (isPlaying) {
      timer = setInterval(
        () => {
          if (currentMessage.isChunk) {
            if (autoSkipChunks) {
              setChunkNum(getTotalChunks(currentMessage));
              setCurrentStep((s) => s + 1);
            } else {
              setChunkNum((prev) => {
                if (prev >= getTotalChunks(currentMessage)) {
                  setCurrentStep((s) => s + 1);
                  return 1;
                }
                return prev + 1;
              });
            }
          } else {
            setCurrentStep((prev) => {
              if (prev >= INITIAL_FLOW_DATA[currentFlow].messages.length - 1) {
                setIsPlaying(false);
                return prev;
              }
              return prev + 1;
            });
          }
        },
        autoSkipChunks ? 1000 : 200
      );
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [
    isPlaying,
    currentFlow,
    currentStep,
    currentMessage,
    chunkNum,
    autoSkipChunks,
  ]);

  const handlePrevious = () => {
    if (currentMessage.isChunk && chunkNum > 1) {
      setChunkNum((prev) => prev - 1);
    } else {
      setCurrentStep((prev) => Math.max(0, prev - 1));
      if (currentStep > 0) {
        const prevMessage =
          INITIAL_FLOW_DATA[currentFlow].messages[currentStep - 1];
        setChunkNum(getTotalChunks(prevMessage));
      }
    }
  };

  const handleNext = () => {
    if (currentMessage.isChunk && chunkNum < totalChunks) {
      if (autoSkipChunks) {
        setChunkNum(totalChunks);
      } else {
        setChunkNum((prev) => prev + 1);
      }
    } else {
      setCurrentStep((prev) =>
        Math.min(INITIAL_FLOW_DATA[currentFlow].messages.length - 1, prev + 1)
      );
      setChunkNum(1);
    }
  };

  return (
    <Card className='w-full max-w-6xl'>
      <CardHeader className='flex flex-row items-center justify-between'>
        <CardTitle>{INITIAL_FLOW_DATA[currentFlow].title}</CardTitle>
        <div className='flex gap-4'>
          <div className='flex gap-2'>
            {Object.keys(INITIAL_FLOW_DATA).map((key) => (
              <button
                key={key}
                onClick={() => {
                  setCurrentFlow(key);
                  setCurrentStep(0);
                  setChunkNum(1);
                  setIsPlaying(false);
                }}
                className={`px-4 py-2 rounded-lg ${
                  currentFlow === key
                    ? 'bg-blue-500 text-white'
                    : 'bg-gray-100 hover:bg-gray-200'
                }`}
              >
                {key.charAt(0).toUpperCase() + key.slice(1)}
              </button>
            ))}
          </div>
          <div className='flex gap-2'>
            <button
              onClick={() => setAutoSkipChunks(!autoSkipChunks)}
              className={`flex items-center gap-1 px-3 py-2 rounded-lg ${
                autoSkipChunks ? 'bg-green-500 text-white' : 'bg-gray-200'
              }`}
            >
              <FastForward className='w-4 h-4' />
              {autoSkipChunks ? 'Fast' : 'Step'}
            </button>
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg ${
                isPlaying ? 'bg-red-500 text-white' : 'bg-blue-500 text-white'
              }`}
            >
              <Play className='w-4 h-4' />
              {isPlaying ? 'Stop' : 'Play'}
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className='space-y-8'>
        <MessageInfo
          message={currentMessage}
          active={true}
          chunkNum={chunkNum}
        />

        {/* Navigation Controls */}
        <div className='flex justify-between items-center'>
          <button
            onClick={handlePrevious}
            disabled={currentStep === 0 && chunkNum === 1}
            className='px-4 py-2 rounded-lg bg-blue-500 text-white disabled:bg-gray-300'
          >
            Previous
          </button>

          {currentMessage.isChunk && (
            <button
              onClick={() => setChunkNum(totalChunks)}
              className='px-4 py-2 rounded-lg bg-green-500 text-white'
            >
              Skip to End
            </button>
          )}

          <button
            onClick={handleNext}
            disabled={
              currentStep ===
                INITIAL_FLOW_DATA[currentFlow].messages.length - 1 &&
              (!currentMessage.isChunk || chunkNum === totalChunks)
            }
            className='px-4 py-2 rounded-lg bg-blue-500 text-white disabled:bg-gray-300'
          >
            Next
          </button>
        </div>
        {/* Progress Indicators */}
        <div className='flex gap-1'>
          {INITIAL_FLOW_DATA[currentFlow].messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex-1 h-1 rounded-full transition-all duration-300 ${
                idx === currentStep
                  ? 'bg-blue-500'
                  : idx < currentStep
                  ? 'bg-gray-300'
                  : 'bg-gray-100'
              }`}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

export default ProtocolVisualization;
